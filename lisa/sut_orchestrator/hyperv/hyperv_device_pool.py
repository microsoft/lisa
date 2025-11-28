# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Dict, List, Optional

from lisa.node import RemoteNode
from lisa.sut_orchestrator.hyperv.get_assignable_devices import HypervAssignableDevices
from lisa.sut_orchestrator.hyperv.schema import (
    DeviceAddressSchema,
    HypervNodeSchema,
    HypervPlatformSchema,
)
from lisa.sut_orchestrator.util.device_pool import BaseDevicePool
from lisa.sut_orchestrator.util.schema import HostDevicePoolSchema, HostDevicePoolType
from lisa.tools import HyperV, PowerShell
from lisa.util import ResourceAwaitableException
from lisa.util.logger import Logger

from .context import DevicePassthroughContext, NodeContext


class HyperVDevicePool(BaseDevicePool):
    def __init__(
        self,
        node: RemoteNode,
        runbook: HypervPlatformSchema,
        log: Logger,
    ) -> None:
        # Device Passthrough configs
        # Mapping of Host Device Passthrough
        self.available_host_devices: Dict[
            HostDevicePoolType, List[DeviceAddressSchema]
        ] = {}
        self.supported_pool_type = [
            HostDevicePoolType.PCI_NIC,
            HostDevicePoolType.PCI_GPU,
        ]
        self._server = node
        self._hyperv_runbook = runbook
        self.log = log

    def create_device_pool(
        self,
        pool_type: HostDevicePoolType,
        vendor_id: str,
        device_id: str,
    ) -> None:
        hv_dev = HypervAssignableDevices(
            host_node=self._server,
            log=self.log,
        )
        devices = hv_dev.get_assignable_devices(
            vendor_id=vendor_id,
            device_id=device_id,
        )
        primary_nic_id_list = self.get_primary_nic_id()
        pool = self.available_host_devices.get(pool_type, [])
        for dev in devices:
            if dev.instance_id not in primary_nic_id_list:
                pool.append(dev)
        self.available_host_devices[pool_type] = pool

    def request_devices(
        self,
        pool_type: HostDevicePoolType,
        count: int,
    ) -> List[DeviceAddressSchema]:
        pool = self.available_host_devices[pool_type]
        if len(pool) < count:
            raise ResourceAwaitableException(
                f"Not enough devices are available under pool: {pool_type}. "
                f"Required count is {count}"
            )
        devices = pool[:count]

        # Update the pool
        pool = pool[count:]
        self.available_host_devices[pool_type] = pool

        return devices

    def release_devices(
        self,
        node_context: NodeContext,
    ) -> None:
        vm_name = node_context.vm_name
        devices_ctx = node_context.passthrough_devices
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

        powershell = self._server.tools[PowerShell]
        for cmd in confing_commands:
            powershell.run_cmdlet(
                cmdlet=cmd,
                force_run=True,
            )

    def get_primary_nic_id(self) -> List[str]:
        powershell = self._server.tools[PowerShell]
        ip: str = self._server.public_address

        # Get the NIC name via IP.
        # We will get vEthernet switch interface name, not actual NIC for baremetal
        cmd = (
            "(Get-NetAdapter | Get-NetIPAddress | Where-Object "
            f"{{$_.IPAddress -eq '{ip}'}}).InterfaceAlias"
        )
        interface_name = powershell.run_cmdlet(
            cmdlet=cmd,
            force_run=True,
        )

        # Get the MAC for above interface
        cmd = (
            "(Get-NetAdapter | Where-Object "
            f"{{$_.Name -eq '{interface_name}'}}).MacAddress"
        )
        mac_address = powershell.run_cmdlet(
            cmdlet=cmd,
            force_run=True,
        )

        # Get all interfaces for above MAC Address
        cmd = (
            "(Get-NetAdapter | Where-Object "
            f"{{$_.MacAddress -eq '{mac_address}'}}).Name"
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
                f"{{$_.Name -eq '{name}'}}).PnPDeviceID"
            )
            interface_device_id = powershell.run_cmdlet(
                cmdlet=cmd,
                force_run=True,
            )
            interface_device_id = interface_device_id.strip()
            pnp_device_id_list.append(interface_device_id)

        return pnp_device_id_list

    def configure_device_passthrough_pool(
        self,
        device_configs: Optional[List[HostDevicePoolSchema]],
    ) -> None:
        super().configure_device_passthrough_pool(
            device_configs=device_configs,
        )

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

        powershell = self._server.tools[PowerShell]
        for cmd in confing_commands:
            powershell.run_cmdlet(
                cmdlet=cmd,
                force_run=True,
            )

    def _set_device_passthrough_node_context(
        self,
        node_context: NodeContext,
        node_runbook: HypervNodeSchema,
        hv: HyperV,
        vm_name: str,
    ) -> None:
        if not node_runbook.device_passthrough:
            return
        hv.enable_device_passthrough(name=vm_name)

        for config in node_runbook.device_passthrough:
            devices = self.request_devices(
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
            node_context.passthrough_devices.append(device_context)
