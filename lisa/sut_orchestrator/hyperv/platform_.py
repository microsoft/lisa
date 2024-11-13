# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from functools import partial
from pathlib import PurePath
from typing import Any, List, Optional, Type, cast

from lisa import feature, schema, search_space
from lisa.environment import Environment
from lisa.node import RemoteNode
from lisa.platform_ import Platform
from lisa.tools import Cp, HyperV, Mkdir, PowerShell
from lisa.util import LisaException, constants
from lisa.util.logger import Logger, get_logger
from lisa.util.parallel import run_in_parallel
from lisa.util.subclasses import Factory

from .. import HYPERV
from .context import NodeContext, get_node_context
from .hyperv_device_pool import HyperVDevicePool
from .schema import HypervNodeSchema, HypervPlatformSchema
from .serial_console import SerialConsole, SerialConsoleLogger
from .source import Source


class _HostCapabilities:
    def __init__(self) -> None:
        self.core_count = 0
        self.allocable_memory_mib = 0


class HypervPlatform(Platform):
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
        self._source_vhd: Optional[PurePath] = None
        self._source_factory = Factory[Source](Source)
        self._source_files: Optional[List[PurePath]] = None

        self.device_pool = HyperVDevicePool(
            node=self._server,
            runbook=self._hyperv_runbook,
            log=self._log,
        )

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

        if len(environment.runbook.nodes_requirement) > 1:
            log.error("Multiple nodes are currently not supported.")
            return False

        nodes_capabilities = self._create_node_capabilities()

        nodes_requirement = []
        for node_space in environment.runbook.nodes_requirement:
            if not node_space.check(nodes_capabilities):
                return False

            requirement = node_space.generate_min_capability(nodes_capabilities)
            nodes_requirement.append(requirement)

        if not self._is_host_resources_enough(nodes_requirement, log):
            return False

        environment.runbook.nodes_requirement = nodes_requirement

        # If Device_passthrough is set in runbook,
        # Configure device passthrough params / Refresh the pool
        self.device_pool.configure_device_passthrough_pool(
            self._hyperv_runbook.device_pools,
        )
        return True

    def _get_host_capabilities(self, log: Logger) -> _HostCapabilities:
        host_cap = _HostCapabilities()

        free_mem_bytes = self._server.tools[PowerShell].run_cmdlet(
            "(Get-CimInstance -ClassName Win32_OperatingSystem).FreePhysicalMemory"
        )
        free_mem_mib = int(free_mem_bytes) // 1024

        host_cap.allocable_memory_mib = free_mem_mib - 2048  # reserve 2 GiB for host

        lp_count = self._server.tools[PowerShell].run_cmdlet(
            "(Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors"
        )
        host_cap.core_count = int(lp_count)

        log.debug(
            f"Host capabilities: {host_cap.core_count} cores, "
            f"{host_cap.allocable_memory_mib} MiB free memory"
        )

        return host_cap

    # Check that the VM requirements can be fulfilled by the host.
    def _is_host_resources_enough(
        self,
        nodes_requirements: List[schema.NodeSpace],
        log: Logger,
    ) -> bool:
        total_required_memory_mib = 0
        total_required_cpus = 0
        host_capabilities = self._host_capabilities

        for node_requirements in nodes_requirements:
            # Calculate the total amount of memory required for all the VMs.
            assert isinstance(node_requirements.memory_mb, int)
            total_required_memory_mib += node_requirements.memory_mb

            # Calculate total number of CPUs required for all the VMs.
            assert isinstance(node_requirements.core_count, int)
            total_required_cpus += node_requirements.core_count

        # Ensure host has enough memory for all the VMs.
        if total_required_memory_mib > host_capabilities.allocable_memory_mib:
            log.error(
                f"Nodes require a total of {total_required_memory_mib} MiB memory. "
                f"Host only has {host_capabilities.allocable_memory_mib} MiB free."
            )
            return False

        # Ensure host has enough CPUs for all the VMs.
        if total_required_cpus > host_capabilities.core_count:
            log.error(
                f"Nodes require a total of {total_required_cpus} CPUs. "
                f"Host only has {host_capabilities.core_count} CPUs."
            )
            return False

        return True

    def _create_node_capabilities(self) -> schema.NodeSpace:
        host_capabilities = self._host_capabilities
        node_capabilities = schema.NodeSpace()
        node_capabilities.name = "hyperv"
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

    def _download_sources(self, log: Logger) -> None:
        if self._source_files:
            return

        if not self._hyperv_runbook.source:
            return

        source = self._source_factory.create_by_runbook(
            self._hyperv_runbook.source, parent_logger=log
        )
        self._source_files = source.download(self._server)

    def _prepare_source_vhd(self, node_runbook: HypervNodeSchema) -> None:
        if self._source_vhd:
            return

        if node_runbook.vhd and node_runbook.vhd.vhd_path:
            self._source_vhd = PurePath(node_runbook.vhd.vhd_path)
        elif self._source_files:
            for artifact_path in self._source_files:
                if artifact_path.suffix == ".vhd" or artifact_path.suffix == ".vhdx":
                    self._source_vhd = PurePath(artifact_path)
                    break

        if not self._source_vhd:
            raise LisaException("No VHD found in node runbook or sources.")

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        if environment.runbook.nodes_requirement is None:
            return  # nothing to deploy?

        normalized_name = constants.NORMALIZE_PATTERN.sub("-", constants.RUN_NAME)
        vm_name_prefix = f"{normalized_name}-e{environment.id}"

        hv = self._server.tools[HyperV]
        default_switch = hv.get_default_external_switch()
        assert default_switch, "No external switch found"

        extra_args = {
            x.command.lower(): x.args for x in self._hyperv_runbook.extra_args
        }

        self._download_sources(log)

        self._console_logger = SerialConsoleLogger(self._server)

        for i, node_space in enumerate(environment.runbook.nodes_requirement):
            node_runbook = node_space.get_extended_runbook(
                HypervNodeSchema, type(self).type_name()
            )

            vm_name = f"{vm_name_prefix}-n{i}"

            node = environment.create_node_from_requirement(node_space)
            assert isinstance(node, RemoteNode)

            self._prepare_source_vhd(node_runbook)
            assert self._source_vhd

            node.name = vm_name

            node_context = get_node_context(node)
            node_context.vm_name = vm_name
            node_context.host = self._server

            node_context.working_path = PurePath(
                self._server.working_path / f"{vm_name}"
            )

            vm_vhd_name = f"{vm_name}{self._source_vhd.suffix}"
            vhd_path = PurePath(node_context.working_path / f"{vm_vhd_name}")

            self._server.tools[Mkdir].create_directory(str(node_context.working_path))

            self._server.tools[Cp].copy(self._source_vhd, vhd_path)

            self._resize_vhd_if_needed(vhd_path, node_runbook)

            assert isinstance(node.capability.core_count, int)
            assert isinstance(node.capability.memory_mb, int)

            com1_pipe_name = f"{vm_name}-com1"
            com1_pipe_path = f"\\\\.\\pipe\\{com1_pipe_name}"

            log.info(f"Serial logs at {node_context.console_log_path}")
            node_context.serial_log_process = self._console_logger.start_logging(
                com1_pipe_name, node_context.console_log_path, log
            )

            hv.create_vm(
                name=vm_name,
                guest_image_path=str(vhd_path),
                switch_name=default_switch.name,
                generation=node_runbook.hyperv_generation,
                cores=node.capability.core_count,
                memory=node.capability.memory_mb,
                secure_boot=False,
                com_ports={
                    1: com1_pipe_path,
                },
                extra_args=extra_args,
                attach_offline_disks=False,
            )
            # perform device passthrough for the VM
            self.device_pool._set_device_passthrough_node_context(
                node_context=node_context,
                node_runbook=node_runbook,
                hv=hv,
                vm_name=vm_name,
            )
            # Start the VM
            hv.start_vm(name=vm_name, extra_args=extra_args)

            ip_addr = hv.get_ip_address(vm_name)
            username = self.runbook.admin_username
            password = self.runbook.admin_password
            node.set_connection_info(
                address=ip_addr, username=username, password=password
            )

    def _resize_vhd_if_needed(
        self, vhd_path: PurePath, node_runbook: HypervNodeSchema
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
        def _delete_node(node_ctx: NodeContext, wait_delete: bool) -> None:
            hv = self._server.tools[HyperV]
            vm_name = node_ctx.vm_name

            # Reassign passthrough devices to host before VM is deleted
            # This will be hot-unplug of device
            if len(node_ctx.passthrough_devices) > 0:
                self.device_pool.release_devices(node_ctx)

            if wait_delete:
                hv.delete_vm(vm_name)
            else:
                hv.delete_vm_async(vm_name)

            assert node_ctx.serial_log_process
            result = node_ctx.serial_log_process.wait_result()
            log.debug(
                f"{vm_name} serial log process exited with {result.exit_code}. "
                f"stdout: {result.stdout}"
            )

        run_in_parallel(
            [
                partial(
                    _delete_node,
                    get_node_context(node),
                    self._hyperv_runbook.wait_delete,
                )
                for node in environment.nodes.list()
            ]
        )
