# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import random
import string
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, List, Type

from lisa import feature, schema, search_space
from lisa.environment import Environment
from lisa.node import RemoteNode
from lisa.platform_ import Platform
from lisa.tools import Cp, HyperV, Ls, PowerShell, Unzip
from lisa.util.logger import Logger, get_logger

from .. import HYPERV
from .context import NodeContext, get_node_context
from .schema import HypervNodeSchema, HypervPlatformSchema
from .serial_console import SerialConsole, SerialConsoleLogger


class _HostCapabilities:
    def __init__(self) -> None:
        self.core_count = 0
        self.free_memory_kib = 0


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
        hyperv_runbook = self.runbook.get_extended_runbook(HypervPlatformSchema)
        assert hyperv_runbook, "platform runbook cannot be empty"
        self._hyperv_runbook = hyperv_runbook

        if len(self._hyperv_runbook.servers) > 1:
            self._log.info(
                "Multiple servers are currently not supported. "
                "Only the first server will be used."
            )

        server = self._hyperv_runbook.servers[0]
        self.server_node = RemoteNode(
            runbook=schema.Node(name="hyperv-server"),
            index=-1,
            logger_name="hyperv-server",
            parent_logger=get_logger("hyperv-platform"),
        )
        self.server_node.set_connection_info(
            address=server.address, username=server.username, password=server.password
        )

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        return self._configure_node_capabilities(environment, log)

    def _configure_node_capabilities(
        self, environment: Environment, log: Logger
    ) -> bool:
        if not environment.runbook.nodes_requirement:
            return True

        host_capabilities = self._get_host_capabilities(log)
        nodes_capabilities = self._create_node_capabilities(host_capabilities)

        nodes_requirement = []
        for node_space in environment.runbook.nodes_requirement:
            if not node_space.check(nodes_capabilities):
                return False

            requirement = node_space.generate_min_capability(nodes_capabilities)
            nodes_requirement.append(requirement)

        environment.runbook.nodes_requirement = nodes_requirement
        return True

    def _get_host_capabilities(self, log: Logger) -> _HostCapabilities:
        host_cap = _HostCapabilities()

        free_mem_bytes = self.server_node.tools[PowerShell].run_cmdlet(
            "(Get-CimInstance -ClassName Win32_OperatingSystem).FreePhysicalMemory"
        )
        host_cap.free_memory_kib = int(free_mem_bytes) // 1024

        lp_count = self.server_node.tools[PowerShell].run_cmdlet(
            "(Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors"
        )
        host_cap.core_count = int(lp_count)

        log.debug(
            f"Host capabilities: {host_cap.core_count} cores, "
            f"{host_cap.free_memory_kib} KiB free memory"
        )

        return host_cap

    # Check that the VM requirements can be fulfilled by the host.
    def _check_host_capabilities(
        self,
        nodes_requirements: List[schema.NodeSpace],
        host_capabilities: _HostCapabilities,
        log: Logger,
    ) -> bool:
        total_required_memory_mib = 0

        for node_requirements in nodes_requirements:
            # Calculate the total amount of memory required for all the VMs.
            assert isinstance(node_requirements.memory_mb, int)
            total_required_memory_mib += node_requirements.memory_mb

        # Ensure host has enough memory for all the VMs.
        total_required_memory_kib = total_required_memory_mib * 1024
        if total_required_memory_kib > host_capabilities.free_memory_kib:
            log.error(
                f"Nodes require a total of {total_required_memory_kib} KiB memory. "
                f"Host only has {host_capabilities.free_memory_kib} KiB free."
            )
            return False

        return True

    def _create_node_capabilities(
        self, host_capabilities: _HostCapabilities
    ) -> schema.NodeSpace:
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

    def _deploy_nodes(self, environment: Environment, log: Logger) -> None:
        if environment.runbook.nodes_requirement is None:
            return  # nothing to deploy?

        test_suffix = "".join(random.choice(string.ascii_uppercase) for _ in range(5))
        vm_name_prefix = f"lisa-{test_suffix}"

        hv = self.server_node.tools[HyperV]
        default_switch = hv.get_first_switch()

        extra_args = {
            x.command.lower(): x.args for x in self._hyperv_runbook.extra_args
        }

        self.console_logger = SerialConsoleLogger(self.server_node)

        for i, node_space in enumerate(environment.runbook.nodes_requirement):
            node_runbook = node_space.get_extended_runbook(
                HypervNodeSchema, type(self).type_name()
            )

            vm_name = f"{vm_name_prefix}-{i}"

            node = environment.create_node_from_requirement(node_space)
            assert isinstance(node, RemoteNode)

            node.name = vm_name

            node_context = get_node_context(node)
            node_context.vm_name = vm_name
            node_context.server_node = self.server_node
            node_context.vhd_local_path = PurePosixPath(node_runbook.vhd)
            node_context.vhd_remote_path = PureWindowsPath(
                self.server_node.working_path / f"{vm_name}-vhd.vhdx"
            )
            node_context.console_log_path = PureWindowsPath(
                self.server_node.working_path / f"{vm_name}-console.log"
            )

            remote_path = node_context.vhd_remote_path
            is_zipped = False
            if node_context.vhd_local_path.suffix == ".zip":
                remote_path = PureWindowsPath(
                    self.server_node.working_path / f"{vm_name}-vhd.zip"
                )
                is_zipped = True

            log.debug("Copying VHD to server")
            self.server_node.shell.copy(node_context.vhd_local_path, remote_path)
            log.debug("Finished copying VHD to server")

            if is_zipped:
                self._unzip_vhd(node_context, remote_path)

            self._resize_vhd_if_needed(node_context.vhd_remote_path, node_runbook)

            assert isinstance(node.capability.core_count, int)
            assert isinstance(node.capability.memory_mb, int)

            com1_pipe_name = f"{vm_name}-com1"
            com1_pipe_path = f"\\\\.\\pipe\\{com1_pipe_name}"

            log.info(f"Serial logs at {node_context.console_log_path}")
            node_context.serial_log_task_mgr = self.console_logger.start_logging(
                com1_pipe_name, node_context.console_log_path, log
            )

            hv.create_vm(
                name=vm_name,
                guest_image_path=str(node_context.vhd_remote_path),
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

    def _unzip_vhd(
        self, node_context: NodeContext, zipped_vhd_path: PureWindowsPath
    ) -> None:
        extraction_path = zipped_vhd_path.parent.joinpath("extracted")
        self.server_node.tools[Unzip].extract(
            str(zipped_vhd_path), str(extraction_path)
        )

        extracted_files = self.server_node.tools[Ls].list(str(extraction_path))
        assert len(extracted_files) == 1

        extracted_vhd = PureWindowsPath(extracted_files[0])
        extracted_vhd = extraction_path.joinpath(extracted_vhd)

        self.server_node.tools[Cp].copy(extracted_vhd, node_context.vhd_remote_path)
        self.server_node.shell.remove(zipped_vhd_path)

    def _resize_vhd_if_needed(
        self, vhd_path: PureWindowsPath, node_runbook: HypervNodeSchema
    ) -> None:
        pwsh = self.server_node.tools[PowerShell]
        vhd_size = int(pwsh.run_cmdlet(f"(Get-VHD -Path {vhd_path}).Size"))
        if vhd_size < node_runbook.osdisk_size_in_gb * 1024 * 1024 * 1024:
            pwsh.run_cmdlet(
                f"Resize-VHD -Path {vhd_path} "
                f"-SizeBytes {node_runbook.osdisk_size_in_gb * 1024 * 1024 * 1024}"
            )

    def _delete_environment(self, environment: Environment, log: Logger) -> None:
        self._delete_nodes(environment, log)

    def _delete_nodes(self, environment: Environment, log: Logger) -> None:
        hv = self.server_node.tools[HyperV]
        for node in environment.nodes.list():
            node_ctx = get_node_context(node)
            vm_name = node_ctx.vm_name

            log.debug(f"Deleting VM {vm_name}")
            hv.delete_vm(vm_name)

            # The script that logs the serial console output exits gracefully
            # on its own after the VM is deleted. So, wait for that to happen.
            assert node_ctx.serial_log_task_mgr
            node_ctx.serial_log_task_mgr.wait_for_all_workers()
