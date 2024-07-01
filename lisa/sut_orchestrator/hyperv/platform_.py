# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from functools import partial
from pathlib import Path, PurePath
from typing import Any, Dict, List, Optional, Type, Union, cast

from lisa import feature, schema, search_space
from lisa.environment import Environment
from lisa.node import RemoteNode
from lisa.platform_ import Platform
from lisa.sut_orchestrator.util.device_pool import BaseDevicePoolImpl
from lisa.sut_orchestrator.util.schema import HostDevicePoolType
from lisa.tools import Cp, HyperV, Mkdir, PowerShell
from lisa.util import LisaException, SkippedException, constants
from lisa.util.logger import Logger, get_logger
from lisa.util.parallel import run_in_parallel
from lisa.util.subclasses import Factory

from .. import HYPERV
from .context import (
    DeviceAddressSchema,
    DevicePassthroughContext,
    NodeContext,
    get_node_context,
)
from .schema import HypervNodeSchema, HypervPlatformSchema
from .serial_console import SerialConsole, SerialConsoleLogger
from .source import Source


class _HostCapabilities:
    def __init__(self) -> None:
        self.core_count = 0
        self.allocable_memory_mib = 0


class HypervPlatform(Platform, BaseDevicePoolImpl):
    # Device Passthrough configs
    # Mapping of Host Device Passthrough
    AVAILABLE_HOST_DEVICES: Dict[HostDevicePoolType, List[DeviceAddressSchema]] = {}
    SUPPORTED_HOST_DEVICE_POOLTYPE = [
        HostDevicePoolType.PCI_NIC,
        HostDevicePoolType.PCI_GPU,
    ]
    POOL_TYPE_TO_DEVICE_PROPERTY = {
        HostDevicePoolType.PCI_NIC: DeviceAddressSchema,
        HostDevicePoolType.PCI_GPU: DeviceAddressSchema,
    }

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

        # Copy pwershell script onto host
        script_name = "get_assignable_devices.ps1"
        src_path = Path(__file__).parent.joinpath(script_name)
        self._assignable_devices_script = self._server.working_path / script_name
        self._server.shell.copy(
            src_path,
            self._assignable_devices_script,
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
        # Configure device passthrough params
        self._configure_device_passthrough_pool(
            self._hyperv_runbook.device_pools,
            self.SUPPORTED_HOST_DEVICE_POOLTYPE,
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

        for record, node_space in enumerate(environment.runbook.nodes_requirement):
            node_runbook = node_space.get_extended_runbook(
                HypervNodeSchema, type(self).type_name()
            )

            vm_name = f"{vm_name_prefix}-n{record}"

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
            )

            # perform device passthrough for the VM
            self._set_device_passthrough_node_context(
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
            if node_ctx.is_device_passthrough_set:
                self._put_devices_into_pool(node_ctx)

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

    def _create_device_pool(
        self,
        pool_type: HostDevicePoolType,
        vendor_id: str,
        device_id: str,
    ) -> None:
        self.AVAILABLE_HOST_DEVICES[pool_type] = []
        powershell = self._server.tools[PowerShell]
        cmdlet = (
            f"{self._assignable_devices_script} "
            f"-vendorId {vendor_id} -deviceId {device_id}"
        )
        stdout = powershell.run_cmdlet(
            cmdlet=cmdlet,
            sudo=True,
            force_run=True,
        ).strip()

        if stdout.find("The list is empty") >= 0:
            return
        else:
            match = re.search(
                r"Assignable Devices Found:(.*)",
                stdout,
                re.DOTALL,
            )
            if match:
                devices_csv_list = match.group(1).strip()
                primary_nic_id_list = self._get_primary_nic_id()
                assert len(primary_nic_id_list) != 0
                for device_record in devices_csv_list.splitlines():
                    device_attrbs = device_record.strip().split(",")
                    assert len(device_attrbs) == 3
                    instance_id = device_attrbs[2].replace('"', "")
                    if instance_id not in primary_nic_id_list:
                        device = self.POOL_TYPE_TO_DEVICE_PROPERTY[pool_type]()
                        device.friendly_name = device_attrbs[0].replace('"', "")
                        device.location_path = device_attrbs[1].replace('"', "")
                        device.instance_id = instance_id

                        # add device to the given pool_type
                        pool = self.AVAILABLE_HOST_DEVICES.get(pool_type, [])
                        pool.append(device)
                        self.AVAILABLE_HOST_DEVICES[pool_type] = pool

    def _get_devices_from_pool(
        self,
        pool_type: HostDevicePoolType,
        count: int,
    ) -> List[DeviceAddressSchema]:
        pool = self.AVAILABLE_HOST_DEVICES[pool_type]
        if len(pool) < count:
            raise SkippedException(
                f"Not enough devices are available under pool: {pool_type}. "
                f"Required count is {count}"
            )
        devices = pool[:count]

        # Update the pool
        pool = pool[count:]
        self.AVAILABLE_HOST_DEVICES[pool_type] = pool

        return devices

    def _put_devices_into_pool(
        self,
        node_context: NodeContext,
    ) -> None:
        self._remove_devices_from_vm(node_context=node_context)

        # Refresh the pool
        self._configure_device_passthrough_pool(
            self._hyperv_runbook.device_pools,
            self.SUPPORTED_HOST_DEVICE_POOLTYPE,
        )

    def _remove_devices_from_vm(
        self,
        node_context: NodeContext,
    ) -> None:
        vm_name = node_context.vm_name
        devices_ctx = node_context.device_passthrough_context
        confing_commands = []
        for ctx in devices_ctx:
            for device in ctx.device_list:
                confing_commands.append(
                    f"Remove-VMAssignableDevice "
                    f"-LocationPath '{device.location_path}' -VMName '{vm_name}'"
                )
                confing_commands.append(
                    f"Mount-VMHostAssignableDevice -LocationPath "
                    f"'{device.location_path}'"
                )
                confing_commands.append(
                    f"Enable-PnpDevice -InstanceId '{device.instance_id}' "
                    "-Confirm:$false"
                )
        self._run_powershell_commands(confing_commands)

    def _assign_devices_to_vm(
        self,
        vm_name: str,
        devices: List[DeviceAddressSchema],
    ) -> None:
        # Assign the devices to the VM
        confing_commands = []
        for device in devices:
            confing_commands.append(
                f"Disable-PnpDevice -InstanceId '{device.instance_id}' -Confirm:$false"
            )
            confing_commands.append(
                f"Dismount-VMHostAssignableDevice -Force "
                f"-LocationPath '{device.location_path}'"
            )
            confing_commands.append(
                f"Add-VMAssignableDevice -LocationPath '{device.location_path}' "
                f"-VMName '{vm_name}'"
            )
        self._run_powershell_commands(confing_commands)

    def _run_powershell_commands(
        self,
        command: Union[str, List[str]],
    ) -> None:
        requested_cmds = []
        if isinstance(command, str):
            requested_cmds.append(command)
        else:
            requested_cmds = command

        powershell = self._server.tools[PowerShell]
        for cmd in requested_cmds:
            powershell.run_cmdlet(
                cmdlet=cmd,
                force_run=True,
            )

    def _get_primary_nic_id(self) -> List[str]:
        powershell = self._server.tools[PowerShell]
        ip: str = self._server.public_address

        # Get the NIC name via IP.
        # We will get vEthernet switch interface name, not actual NIC for baremetal
        cmd = (
            "(Get-NetAdapter | Get-NetIPAddress | Where-Object "
            f"{{ $_.IPAddress -eq '{ip}' }}).InterfaceAlias"
        )
        interface_name = powershell.run_cmdlet(
            cmdlet=cmd,
            force_run=True,
        )

        # Get the MAC for above interface
        cmd = (
            "(Get-NetAdapter | Where-Object "
            f"{{ $_.Name -eq '{interface_name}' }}).MacAddress"
        )
        mac_address = powershell.run_cmdlet(
            cmdlet=cmd,
            force_run=True,
        )

        # Get all interfaces for above MAC Address
        cmd = (
            "(Get-NetAdapter | Where-Object "
            f"{{ $_.MacAddress -eq '{mac_address}' }}).Name"
        )
        inf_names_str = powershell.run_cmdlet(
            cmdlet=cmd,
            force_run=True,
        )
        inf_names: List[str] = inf_names_str.strip().splitlines()

        # Get device id for all above interface names we got
        pnp_device_id_list: List[str] = []
        for name in inf_names:
            cmd = (
                "(Get-NetAdapter | Where-Object "
                f"{{ $_.Name -eq '{name}' }}).PnPDeviceID"
            )
            interface_device_id = powershell.run_cmdlet(
                cmdlet=cmd,
                force_run=True,
            )
            interface_device_id = interface_device_id.strip()
            pnp_device_id_list.append(interface_device_id)

        return pnp_device_id_list

    def _set_device_passthrough_node_context(
        self,
        node_context: NodeContext,
        node_runbook: HypervNodeSchema,
        hv: HyperV,
        vm_name: str,
    ) -> None:
        if node_runbook.device_passthrough:
            node_context.is_device_passthrough_set = True
            hv.enable_device_passthrough(name=vm_name)

            for config in node_runbook.device_passthrough:
                devices = self._get_devices_from_pool(
                    pool_type=config.pool_type,
                    count=config.count,
                )
                self._assign_devices_to_vm(
                    vm_name=vm_name,
                    devices=devices,
                )
                device_context = DevicePassthroughContext()
                device_context.pool_type = config.pool_type
                device_context.device_list = devices
                node_context.device_passthrough_context.append(device_context)
