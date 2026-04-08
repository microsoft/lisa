# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import io
import os
import shlex
import tempfile
import time
from pathlib import Path, PurePath
from typing import Any, List, Optional, Type, cast

import pycdlib
import uuid
import yaml

from lisa import constants, schema, search_space
from lisa.feature import Features
from lisa.node import Node, RemoteNode
from lisa.tools import Kill, Ls, Mkdir, OpenVmm
from lisa.tools.openvmm import OpenVmmLaunchConfig
from lisa.util import LisaException, get_public_key_data
from lisa.util.logger import Logger
from lisa.util.shell import wait_tcp_port_ready

from .. import OPENVMM
from .context import get_node_context
from .schema import OPENVMM_NETWORK_MODE_USER, OpenVmmGuestNodeSchema
from .start_stop import StartStop


OPENVMM_CONNECTION_TIMEOUT = 300


def _countspace_to_int(value: search_space.CountSpace) -> int:
    chosen = search_space.choose_value_countspace(value, value)
    assert isinstance(chosen, int), f"expected int countspace, got {type(chosen)}"
    return chosen


class OpenVmmController:
    def __init__(self, node: "OpenVmmGuestNode") -> None:
        self._node = node
        assert node.parent, "OpenVMM guest node must have a parent host node"
        self.host_node = node.parent
        self._log = node.log

    @classmethod
    def type_name(cls) -> str:
        return OPENVMM

    @classmethod
    def supported_features(cls) -> List[Type[Any]]:
        return [StartStop]

    def resolve_guest_artifact_path(
        self, source_path: str, is_remote_path: bool, working_path: PurePath
    ) -> str:
        if not source_path:
            return ""

        if is_remote_path or not self.host_node.is_remote:
            return source_path

        source = Path(source_path)
        if not source.exists():
            raise LisaException(f"file does not exist: {source_path}")

        destination = working_path / source.name
        if not self.host_node.tools[Ls].path_exists(str(destination), sudo=True):
            self.host_node.shell.copy(source, destination)
        return str(destination)

    def get_openvmm_tool(self, binary_path: str) -> OpenVmm:
        openvmm = cast(OpenVmm, OpenVmm.create(self.host_node))
        openvmm.initialize()
        requested_path = binary_path or "openvmm"
        openvmm.set_binary_path(requested_path)
        if not openvmm.exists and requested_path != "openvmm":
            self._log.debug(
                f"OpenVMM binary '{requested_path}' was not found; "
                "falling back to 'openvmm' from PATH"
            )
            openvmm.set_binary_path("openvmm")
        return openvmm

    def launch(self, node: "OpenVmmGuestNode", log: Logger) -> None:
        runbook = cast(OpenVmmGuestNodeSchema, node.runbook)
        node_context = get_node_context(node)
        launch_config = OpenVmmLaunchConfig(
            uefi_firmware_path=node_context.uefi_firmware_path,
            disk_img_path=node_context.disk_img_path,
            dvd_disk_paths=(
                [node_context.cloud_init_file_path]
                if node_context.cloud_init_file_path
                else []
            ),
            processors=_countspace_to_int(node.capability.core_count),
            memory_mb=_countspace_to_int(node.capability.memory_mb),
            network_mode=runbook.network.mode,
            network_cidr=runbook.network.consomme_cidr,
            serial_mode=runbook.serial.mode,
            serial_path=node_context.console_log_file_path,
            extra_args=runbook.extra_args,
            stdout_path=node_context.launcher_log_file_path,
            stderr_path=node_context.launcher_log_file_path,
        )
        openvmm = self.get_openvmm_tool(runbook.openvmm_binary)
        node_context.command_line = openvmm.build_command(launch_config)
        node_context.process_id = openvmm.launch_vm(
            launch_config,
            cwd=PurePath(node_context.working_path),
            sudo=False,
        )
        self._ensure_process_running(node_context)
        log.debug(
            f"Launched OpenVMM VM '{node_context.vm_name}' with pid "
            f"{node_context.process_id}"
        )

    def create_node_cloud_init_iso(self, node: "OpenVmmGuestNode") -> None:
        runbook = cast(OpenVmmGuestNodeSchema, node.runbook)
        node_context = get_node_context(node)

        user: dict[str, Any] = {
            "name": runbook.username,
            "shell": "/bin/bash",
            "sudo": ["ALL=(ALL) NOPASSWD:ALL"],
            "groups": ["sudo"],
        }
        if runbook.private_key_file:
            user["ssh_authorized_keys"] = [
                get_public_key_data(runbook.private_key_file)
            ]

        user_data: dict[str, Any] = {
            "users": ["default", user],
        }
        if runbook.username == "root":
            user_data["disable_root"] = False
        if runbook.password:
            user["lock_passwd"] = False
            user["plain_text_passwd"] = runbook.password
            user_data["ssh_pwauth"] = True

        for extra_user_data in node_context.extra_cloud_init_user_data:
            for key, value in extra_user_data.items():
                existing_value = user_data.get(key)
                if not existing_value:
                    user_data[key] = value
                elif isinstance(existing_value, dict) and isinstance(value, dict):
                    existing_value.update(value)
                elif isinstance(existing_value, list) and isinstance(value, list):
                    existing_value.extend(value)
                else:
                    user_data[key] = value

        meta_data = {
            "instance-id": f"{node_context.vm_name}-{uuid.uuid4().hex}",
            "local-hostname": node_context.vm_name,
        }

        user_data_string = "#cloud-config\n" + yaml.safe_dump(user_data)
        meta_data_string = yaml.safe_dump(meta_data)

        tmp_dir = tempfile.TemporaryDirectory()
        try:
            iso_path = os.path.join(tmp_dir.name, "cloud-init.iso")
            self._create_iso(
                iso_path,
                [
                    ("/user-data", user_data_string),
                    ("/meta-data", meta_data_string),
                ],
            )
            self.host_node.shell.copy(
                Path(iso_path), PurePath(node_context.cloud_init_file_path)
            )
        finally:
            tmp_dir.cleanup()

    def _create_iso(self, file_path: str, files: List[tuple[str, str]]) -> None:
        iso = pycdlib.PyCdlib()
        iso.new(joliet=3, vol_ident="cidata")

        for index, (path, contents) in enumerate(files):
            contents_data = contents.encode()
            iso.add_fp(
                io.BytesIO(contents_data),
                len(contents_data),
                f"/{index}.;1",
                joliet_path=path,
            )

        iso.write(file_path)
        iso.close()

    def configure_connection(self, node: RemoteNode, log: Logger) -> None:
        runbook = cast(OpenVmmGuestNodeSchema, node.runbook)
        node.set_connection_info(
            address=runbook.network.connection_address,
            public_address=runbook.network.connection_address,
            username=runbook.username,
            password=runbook.password,
            private_key_file=runbook.private_key_file,
            port=runbook.network.ssh_port,
            public_port=runbook.network.ssh_port,
        )
        try:
            wait_tcp_port_ready(
                runbook.network.connection_address,
                runbook.network.ssh_port,
                log=log,
                timeout=OPENVMM_CONNECTION_TIMEOUT,
            )
        except Exception as identifier_error:
            raise LisaException(
                "OpenVMM guest SSH port did not become reachable at "
                f"{runbook.network.connection_address}:{runbook.network.ssh_port}"
            ) from identifier_error

    def stop_node(self, node: Node, wait: bool = True) -> None:
        node_context = get_node_context(node)
        if node.is_connected:
            node.execute(
                "shutdown -P now",
                shell=True,
                sudo=True,
                no_info_log=True,
                no_error_log=True,
                expected_exit_code=None,
            )

        if wait and node_context.process_id:
            self._wait_for_process_exit(node_context.process_id)

        if node_context.process_id:
            self.host_node.tools[Kill].by_pid(
                node_context.process_id,
                ignore_not_exist=True,
            )
            node_context.process_id = ""

    def start_node(self, node: "OpenVmmGuestNode", wait: bool = True) -> None:
        self.launch(node, node.log)
        self.configure_connection(node, node.log)

    def restart_node(self, node: "OpenVmmGuestNode", wait: bool = True) -> None:
        self.stop_node(node, wait=wait)
        self.start_node(node, wait=wait)

    def _wait_for_process_exit(self, process_id: str, timeout: int = 60) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self._is_process_running(process_id):
                return
            time.sleep(1)

    def _ensure_process_running(
        self, node_context: Any, grace_period: int = 2
    ) -> None:
        if grace_period > 0:
            time.sleep(grace_period)

        if self._is_process_running(node_context.process_id):
            return

        raise LisaException(
            "OpenVMM process exited immediately after launch. "
            f"Check {node_context.launcher_log_file_path} on the host for details."
        )

    def _is_process_running(self, process_id: str) -> bool:
        if not process_id:
            return False

        result = self.host_node.execute(
            f"kill -0 {shlex.quote(process_id)}",
            shell=True,
            sudo=True,
            no_info_log=True,
            no_error_log=True,
            expected_exit_code=None,
        )
        return result.exit_code == 0


class OpenVmmGuestNode(RemoteNode):
    def __init__(
        self,
        runbook: schema.Node,
        index: int,
        logger_name: str,
        is_test_target: bool = True,
        base_part_path: Optional[Path] = None,
        parent_logger: Optional[Logger] = None,
        encoding: str = "utf-8",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            runbook=runbook,
            index=index,
            logger_name=logger_name,
            is_test_target=is_test_target,
            base_part_path=base_part_path,
            parent_logger=parent_logger,
            encoding=encoding,
            **kwargs,
        )
        self._openvmm_controller = OpenVmmController(self)
        self._initialize_capability()
        self.features = Features(self, cast(Any, self._openvmm_controller))

    @classmethod
    def type_name(cls) -> str:
        return OPENVMM

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return OpenVmmGuestNodeSchema

    def cleanup(self) -> None:
        try:
            self._openvmm_controller.stop_node(self, wait=False)
        except Exception as identifier:
            self.log.debug(f"failed to stop OpenVMM guest during cleanup: {identifier}")
        super().cleanup()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._provision()
        super()._initialize(*args, **kwargs)

    def _provision(self) -> None:
        assert self.parent, "OpenVMM guest node must have a parent host node"
        self.parent.initialize()
        runbook = cast(OpenVmmGuestNodeSchema, self.runbook)

        host_node = self.parent
        openvmm = self._openvmm_controller.get_openvmm_tool(runbook.openvmm_binary)
        if not openvmm.exists:
            raise LisaException(
                f"OpenVMM binary not found on host: {runbook.openvmm_binary}. "
                "Use the openvmm_installer transformer before provisioning guests."
            )

        vm_name = f"{self.parent.name or 'host'}-{self.name or f'g{self.index}'}"
        node_context = get_node_context(self)
        node_context.vm_name = vm_name
        node_context.host = host_node

        working_path = PurePath(runbook.lisa_working_dir, vm_name)
        node_context.working_path = str(working_path)
        host_node.tools[Mkdir].create_directory(str(working_path))

        assert runbook.uefi, "UEFI settings should be validated in schema"
        node_context.uefi_firmware_path = (
            self._openvmm_controller.resolve_guest_artifact_path(
                runbook.uefi.firmware_path,
                runbook.uefi.firmware_is_remote_path,
                working_path,
            )
        )

        if runbook.disk_img:
            node_context.disk_img_path = (
                self._openvmm_controller.resolve_guest_artifact_path(
                    runbook.disk_img,
                    runbook.disk_img_is_remote_path,
                    working_path,
                )
            )

        if runbook.cloud_init:
            node_context.cloud_init_file_path = str(working_path / "cloud-init.iso")

            extra_user_data = runbook.cloud_init.extra_user_data
            if extra_user_data:
                if isinstance(extra_user_data, str):
                    extra_user_data = [extra_user_data]

                for relative_file_path in extra_user_data:
                    if not relative_file_path:
                        continue

                    file_path = constants.RUNBOOK_PATH.joinpath(relative_file_path)
                    with open(file_path, "r") as file:
                        node_context.extra_cloud_init_user_data.append(
                            yaml.safe_load(file)
                        )

            self._openvmm_controller.create_node_cloud_init_iso(self)

        node_context.launcher_log_file_path = str(working_path / "openvmm-launcher.log")
        node_context.console_log_file_path = str(working_path / "openvmm-console.log")
        node_context.ssh_port = runbook.network.ssh_port

        if runbook.network.mode != OPENVMM_NETWORK_MODE_USER:
            raise LisaException(
                "base OpenVMM orchestrator support requires user-mode networking"
            )

        self._openvmm_controller.launch(self, self.log)
        self._openvmm_controller.configure_connection(self, self.log)

    def _initialize_capability(self) -> None:
        if not self.capability.features:
            self.capability.features = search_space.SetSpace[schema.FeatureSettings](
                is_allow_set=True
            )
        if not any(
            feature.type == StartStop.name() for feature in self.capability.features
        ):
            self.capability.features.add(
                schema.FeatureSettings.create(StartStop.name())
            )

    def _openvmm_stop(self, wait: bool = True) -> None:
        self._openvmm_controller.stop_node(self, wait=wait)

    def _openvmm_start(self, wait: bool = True) -> None:
        self._openvmm_controller.start_node(self, wait=wait)

    def _openvmm_restart(self, wait: bool = True) -> None:
        self._openvmm_controller.restart_node(self, wait=wait)
