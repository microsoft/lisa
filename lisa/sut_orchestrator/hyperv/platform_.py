# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import random
import string
from pathlib import PurePath, PureWindowsPath
from typing import Any, List, Optional, Type, cast

from lisa import feature, schema, search_space
from lisa.environment import Environment
from lisa.node import RemoteNode
from lisa.platform_ import Platform
from lisa.tools import Cp, HyperV, Ls, Mkdir, PowerShell, Unzip
from lisa.util.logger import Logger, get_logger

from .. import HYPERV
from .context import get_node_context
from .schema import HypervNodeSchema, HypervPlatformSchema
from .serial_console import SerialConsole, SerialConsoleLogger


class _HostCapabilities:
    def __init__(self) -> None:
        self.core_count = 0
        self.free_memory_mib = 0


class HypervPlatform(Platform):
    def __init__(
        self,
        runbook: schema.Platform,
    ) -> None:
        super().__init__(runbook=runbook)

    @classmethod
    def type_name(cls) -> str:
        return HYPERV

    @classmethod
    def supported_features(cls) -> List[Type[feature.Feature]]:
        return [SerialConsole]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._hyperv_runbook = self._get_hyperv_runbook()
        self._server = self._initialize_server_node()
        self._host_capabilities = self._get_host_capabilities(self._log)
        self._source_vhd: Optional[PureWindowsPath] = None

    def _get_hyperv_runbook(self) -> HypervPlatformSchema:
        hyperv_runbook = self.runbook.get_extended_runbook(HypervPlatformSchema)
        assert hyperv_runbook, "platform runbook cannot be empty"
        return cast(HypervPlatformSchema, hyperv_runbook)

    def _initialize_server_node(self) -> RemoteNode:
        assert self._hyperv_runbook, "hyperv runbook cannot be empty"

        if len(self._hyperv_runbook.servers) > 1:
            self._log.info(
                "Multiple servers are currently not supported. "
                "Only the first server will be used."
            )

        server_runbook = self._hyperv_runbook.servers[0]
        server_node = RemoteNode(
            runbook=schema.Node(name="hyperv"),
            index=-1,
            logger_name="hyperv",
            parent_logger=get_logger("hyperv"),
        )

        server_node.set_connection_info(
            address=server_runbook.address,
            username=server_runbook.username,
            password=server_runbook.password,
        )

        return server_node

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        if not environment.runbook.nodes_requirement:
            return True

        nodes_capabilities = self._create_node_capabilities()

        nodes_requirement = []
        for node_space in environment.runbook.nodes_requirement:
            if not node_space.check(nodes_capabilities):
                return False

            requirement = node_space.generate_min_capability(nodes_capabilities)
            nodes_requirement.append(requirement)

        if not self._check_host_capabilities(nodes_requirement, log):
            return False

        environment.runbook.nodes_requirement = nodes_requirement
        return True

    def _get_host_capabilities(self, log: Logger) -> _HostCapabilities:
        host_cap = _HostCapabilities()

        free_mem_bytes = self._server.tools[PowerShell].run_cmdlet(
            "(Get-CimInstance -ClassName Win32_OperatingSystem).FreePhysicalMemory"
        )
        host_cap.free_memory_mib = int(free_mem_bytes) // 1024

        lp_count = self._server.tools[PowerShell].run_cmdlet(
            "(Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors"
        )
        host_cap.core_count = int(lp_count)

        log.debug(
            f"Host capabilities: {host_cap.core_count} cores, "
            f"{host_cap.free_memory_mib} MiB free memory"
        )

        return host_cap

    # Check that the VM requirements can be fulfilled by the host.
    def _check_host_capabilities(
        self,
        nodes_requirements: List[schema.NodeSpace],
        log: Logger,
    ) -> bool:
        total_required_memory_mib = 0
        host_capabilities = self._host_capabilities

        for node_requirements in nodes_requirements:
            # Calculate the total amount of memory required for all the VMs.
            assert isinstance(node_requirements.memory_mb, int)
            total_required_memory_mib += node_requirements.memory_mb

        # Ensure host has enough memory for all the VMs.
        if total_required_memory_mib > host_capabilities.free_memory_mib:
            log.error(
                f"Nodes require a total of {total_required_memory_mib} MiB memory. "
                f"Host only has {host_capabilities.free_memory_mib} MiB free."
            )
            return False

        return True

    def _create_node_capabilities(self) -> schema.NodeSpace:
        host_capabilities = self._host_capabilities
        node_capabilities = schema.NodeSpace()
        node_capabilities.name = "Hyper-V"
        node_capabilities.node_count = 1
        node_capabilities.core_count = search_space.IntRange(
            min=1, max=host_capabilities.core_count
        )
        node_capabilities.disk = schema.DiskOptionSettings(
            data_disk_count=search_space.IntRange(min=0),
            data_disk_size=search_space.IntRange(min=1),
        )
        node_capabilities.network_interface = schema.NetworkInterfaceOptionSettings()
        node_capabilities.network_interface.max_nic_count = 1
        node_capabilities.network_interface.nic_count = 1
        node_capabilities.gpu_count = 0
        node_capabilities.features = search_space.SetSpace[schema.FeatureSettings](
            is_allow_set=True,
            items=[
                schema.FeatureSettings.create(SerialConsole.name()),
            ],
        )

        return node_capabilities

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        self._deploy_nodes(environment, log)

    def _prepare_common_vhd(self, vhd_local_path: PurePath, log: Logger) -> None:
        if self._source_vhd:
            return

        vhd_remote_path = PureWindowsPath(
            self._server.working_path / f"common_vhd.{vhd_local_path.suffix}"
        )

        is_zipped = False
        if vhd_local_path.suffix == ".zip":
            is_zipped = True
            vhd_remote_path = PureWindowsPath(
                self._server.working_path / "zipped_vhd.zip"
            )

        log.debug("Copying VHD to server")
        self._server.shell.copy(vhd_local_path, vhd_remote_path)
        log.debug("Finished copying VHD to server")

        if is_zipped:
            vhd_remote_path = self._unzip_vhd(vhd_remote_path)

        self._source_vhd = vhd_remote_path

    def _deploy_nodes(self, environment: Environment, log: Logger) -> None:
        if environment.runbook.nodes_requirement is None:
            return  # nothing to deploy?

        test_suffix = "".join(random.choice(string.ascii_uppercase) for _ in range(5))
        vm_name_prefix = f"lisa-{test_suffix}"

        hv = self._server.tools[HyperV]
        default_switch = hv.get_first_switch()

        extra_args = {
            x.command.lower(): x.args for x in self._hyperv_runbook.extra_args
        }

        self._console_logger = SerialConsoleLogger(self._server)

        for i, node_space in enumerate(environment.runbook.nodes_requirement):
            node_runbook = node_space.get_extended_runbook(
                HypervNodeSchema, type(self).type_name()
            )

            vm_name = f"{vm_name_prefix}-{i}"

            node = environment.create_node_from_requirement(node_space)
            assert isinstance(node, RemoteNode)

            self._prepare_common_vhd(PurePath(node_runbook.vhd), log)
            assert self._source_vhd

            node.name = vm_name

            node_context = get_node_context(node)
            node_context.vm_name = vm_name
            node_context.host = self._server

            node_context.working_path = PureWindowsPath(
                self._server.working_path / f"{vm_name}"
            )

            vm_vhd_name = f"{vm_name}.{self._source_vhd.suffix}"
            vhd_path = PureWindowsPath(self._server.working_path / f"{vm_vhd_name}")

            self._server.tools[Mkdir].create_directory(str(node_context.working_path))

            self._server.tools[Cp].copy(self._source_vhd, vhd_path)

            self._resize_vhd_if_needed(vhd_path, node_runbook)

            assert isinstance(node.capability.core_count, int)
            assert isinstance(node.capability.memory_mb, int)

            com1_pipe_name = f"{vm_name}-com1"
            com1_pipe_path = f"\\\\.\\pipe\\{com1_pipe_name}"

            log.info(f"Serial logs at {node_context.console_log_path}")
            node_context.serial_log_task_mgr = self._console_logger.start_logging(
                com1_pipe_name, node_context.console_log_path, log
            )

            hv.create_vm(
                name=vm_name,
                guest_image_path=str(vhd_path),
                switch_name=default_switch,
                generation=node_runbook.hyperv_generation,
                cores=node.capability.core_count,
                memory=node.capability.memory_mb,
                secure_boot=False,
                com_ports={
                    1: com1_pipe_path,
                },
                extra_args=extra_args,
            )

            ip_addr = hv.get_ip_address(vm_name)
            username = self.runbook.admin_username
            password = self.runbook.admin_password
            node.set_connection_info(
                address=ip_addr, username=username, password=password
            )

    def _unzip_vhd(self, zipped_vhd_path: PureWindowsPath) -> PureWindowsPath:
        extraction_path = zipped_vhd_path.parent.joinpath("common_vhd")
        self._server.tools[Unzip].extract(str(zipped_vhd_path), str(extraction_path))

        extracted_files = self._server.tools[Ls].list(str(extraction_path))
        assert len(extracted_files) == 1

        extracted_vhd = PureWindowsPath(extracted_files[0])
        extracted_vhd = extraction_path.joinpath(extracted_vhd)

        self._server.shell.remove(zipped_vhd_path)

        return extracted_vhd

    def _resize_vhd_if_needed(
        self, vhd_path: PureWindowsPath, node_runbook: HypervNodeSchema
    ) -> None:
        pwsh = self._server.tools[PowerShell]
        vhd_size = int(pwsh.run_cmdlet(f"(Get-VHD -Path {vhd_path}).Size"))
        if vhd_size < node_runbook.osdisk_size_in_gb * 1024 * 1024 * 1024:
            pwsh.run_cmdlet(
                f"Resize-VHD -Path {vhd_path} "
                f"-SizeBytes {node_runbook.osdisk_size_in_gb * 1024 * 1024 * 1024}"
            )

    def _delete_environment(self, environment: Environment, log: Logger) -> None:
        self._delete_nodes(environment, log)

    def _delete_nodes(self, environment: Environment, log: Logger) -> None:
        hv = self._server.tools[HyperV]
        for node in environment.nodes.list():
            node_ctx = get_node_context(node)
            vm_name = node_ctx.vm_name

            log.debug(f"Deleting VM {vm_name}")
            hv.delete_vm(vm_name)

            # The script that logs the serial console output exits gracefully
            # on its own after the VM is deleted. So, wait for that to happen.
            assert node_ctx.serial_log_task_mgr
            node_ctx.serial_log_task_mgr.wait_for_all_workers()
