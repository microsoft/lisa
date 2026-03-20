# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any, Dict, List, Optional, cast

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
from lisa.util import LisaException, ResourceAwaitableException
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
        self._append_devices_to_pool(pool_type=pool_type, devices=devices)

    def create_device_pool_from_pci_addresses(
        self,
        pool_type: HostDevicePoolType,
        pci_addr_list: List[str],
    ) -> None:
        raise LisaException(
            "Hyper-V device pools do not support 'pci_bdf'. Use vendor_id/"
            "device_id matching or 'location_path' for DDA selection."
        )

    def create_device_pool_from_location_paths(
        self,
        pool_type: HostDevicePoolType,
        location_paths: List[str],
    ) -> None:
        self._restore_devices_to_host(location_paths)
        hv_dev = HypervAssignableDevices(
            host_node=self._server,
            log=self.log,
        )
        devices = hv_dev.get_assignable_devices_by_location_paths(location_paths)
        self._append_devices_to_pool(pool_type=pool_type, devices=devices)

    def _restore_devices_to_host(self, location_paths: List[str]) -> None:
        for location_path in location_paths:
            normalized_path = location_path.strip()
            if not normalized_path:
                continue

            self._restore_device_to_host(normalized_path)

    def _restore_device_to_host(self, location_path: str) -> None:
        powershell = self._server.tools[PowerShell]
        hv = self._server.tools[HyperV]

        assigned_vm_names = self._get_assigned_vm_names(location_path)
        for vm_name in assigned_vm_names:
            vm_state = self._get_vm_state(vm_name)
            if vm_state and vm_state.lower() != "off":
                self.log.info(
                    f"Stopping VM '{vm_name}' to reclaim passthrough device "
                    f"'{location_path}'"
                )
                hv.stop_vm(vm_name, is_graceful=False)

            self.log.info(
                f"Reclaiming passthrough device '{location_path}' from VM "
                f"'{vm_name}'"
            )
            escaped_vm_name = vm_name.replace("'", "''")
            escaped_location_path = location_path.replace("'", "''")
            powershell.run_cmdlet(
                cmdlet=(
                    "Remove-VMAssignableDevice "
                    f"-LocationPath '{escaped_location_path}' "
                    f"-VMName '{escaped_vm_name}'"
                ),
                force_run=True,
            )

        escaped_location_path = location_path.replace("'", "''")
        powershell.run_cmdlet(
            cmdlet=(
                "Mount-VMHostAssignableDevice "
                f"-LocationPath '{escaped_location_path}'"
            ),
            force_run=True,
            fail_on_error=False,
        )

        pnp_device = self._get_pnp_device_by_location_path(location_path)
        if not pnp_device:
            return

        instance_id = str(pnp_device.get("InstanceId", "") or "").strip()
        config_manager_error_code = str(
            pnp_device.get("ConfigManagerErrorCode", "") or ""
        ).strip()
        if instance_id and self._is_pnp_device_disabled(config_manager_error_code):
            self.log.info(
                f"Enabling disabled host device '{instance_id}' for location "
                f"path '{location_path}'"
            )
            escaped_instance_id = instance_id.replace("'", "''")
            powershell.run_cmdlet(
                cmdlet=(
                    f"Enable-PnpDevice -InstanceId '{escaped_instance_id}' "
                    "-Confirm:$false"
                ),
                force_run=True,
            )

    def _is_pnp_device_disabled(self, config_manager_error_code: Any) -> bool:
        normalized_code = str(config_manager_error_code or "").strip().upper()
        return normalized_code in {"22", "CM_PROB_DISABLED"}

    def _get_assigned_vm_names(self, location_path: str) -> List[str]:
        escaped_location_path = location_path.replace("'", "''")
        powershell = self._server.tools[PowerShell]
        stdout = powershell.run_cmdlet(
            cmdlet=(
                f"$target = '{escaped_location_path}'; "
                "Get-VM | ForEach-Object { "
                "$vmName = $_.Name; "
                "if (Get-VMAssignableDevice -VMName $vmName -LocationPath $target "
                "-ErrorAction SilentlyContinue) { "
                "Write-Output $vmName "
                "} "
                "}"
            ),
            force_run=True,
        )
        return [line.strip() for line in stdout.splitlines() if line.strip()]

    def _get_vm_state(self, vm_name: str) -> str:
        escaped_vm_name = vm_name.replace("'", "''")
        powershell = self._server.tools[PowerShell]
        state = powershell.run_cmdlet(
            cmdlet=f"(Get-VM -Name '{escaped_vm_name}').State",
            force_run=True,
            fail_on_error=False,
        )
        return str(state or "").strip()

    def _get_pnp_device_by_location_path(
        self, location_path: str
    ) -> Optional[Dict[str, Any]]:
        escaped_location_path = location_path.replace("'", "''")
        powershell = self._server.tools[PowerShell]
        output: Any = powershell.run_cmdlet(
            cmdlet=(
                f"$target = '{escaped_location_path}'; "
                "Get-PnpDevice -PresentOnly | "
                "Where-Object {$_.InstanceId -like 'PCI\\*'} | "
                "ForEach-Object { "
                "$locationPathData = $null; "
                "try { "
                "$locationPathData = (Get-PnpDeviceProperty -InstanceId $_.InstanceId "
                "'DEVPKEY_Device_LocationPaths' -ErrorAction Stop).Data; "
                "} catch { } "
                "$locationPaths = @(); "
                "if ($locationPathData -is [System.Array]) { "
                "$locationPaths = @($locationPathData); "
                "} elseif ($null -ne $locationPathData) { "
                "$locationPaths = @([string]$locationPathData); "
                "} "
                "if ($locationPaths -contains $target) { "
                "[PSCustomObject]@{ "
                "FriendlyName = $_.FriendlyName; "
                "InstanceId = $_.InstanceId; "
                "ConfigManagerErrorCode = $_.ConfigManagerErrorCode "
                "} "
                "} "
                "}"
            ),
            force_run=True,
            output_json=True,
            fail_on_error=False,
        )

        if not output:
            return None

        if isinstance(output, list):
            output_list = cast(List[Dict[str, Any]], output)
            if len(output_list) > 1:
                raise LisaException(
                    "Multiple PnP devices matched Hyper-V location path "
                    f"'{location_path}'"
                )
            if not output_list:
                return None
            output = output_list[0]

        if not isinstance(output, dict):
            return None

        return cast(Dict[str, Any], output)

    def _append_devices_to_pool(
        self,
        pool_type: HostDevicePoolType,
        devices: List[DeviceAddressSchema],
    ) -> None:
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
        escaped_vm_name = vm_name.replace("'", "''")
        config_commands: List[str] = []
        for ctx in devices_ctx:
            for device in ctx.device_list:
                escaped_location_path = device.location_path.replace("'", "''")
                escaped_instance_id = device.instance_id.replace("'", "''")
                config_commands.append(
                    f"Remove-VMAssignableDevice "
                    f"-LocationPath '{escaped_location_path}' "
                    f"-VMName '{escaped_vm_name}'"
                )
                config_commands.append(
                    f"Mount-VMHostAssignableDevice -LocationPath "
                    f"'{escaped_location_path}'"
                )
                config_commands.append(
                    f"Enable-PnpDevice -InstanceId '{escaped_instance_id}' "
                    "-Confirm:$false"
                )

        powershell = self._server.tools[PowerShell]
        for cmd in config_commands:
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
            "(Get-NetIPAddress | Where-Object "
            f"{{$_.IPAddress -eq '{ip}'}} | "
            "Select-Object -First 1 -ExpandProperty InterfaceAlias)"
        )
        interface_name = powershell.run_cmdlet(
            cmdlet=cmd,
            force_run=True,
        ).strip()
        if not interface_name:
            raise LisaException(
                f"Could not find a Hyper-V management interface for IP '{ip}'"
            )
        escaped_interface_name = interface_name.replace("'", "''")

        # Get the MAC for above interface
        cmd = (
            "(Get-NetAdapter | Where-Object "
            f"{{$_.Name -eq '{escaped_interface_name}'}} | "
            "Select-Object -First 1 -ExpandProperty MacAddress)"
        )
        mac_address = powershell.run_cmdlet(
            cmdlet=cmd,
            force_run=True,
        ).strip()
        if not mac_address:
            raise LisaException(
                "Could not resolve the MAC address for Hyper-V management "
                f"interface '{interface_name}'"
            )

        # Get all interfaces for above MAC Address
        cmd = (
            "(Get-NetAdapter | Where-Object "
            f"{{$_.MacAddress -eq '{mac_address}'}} | "
            "Select-Object -ExpandProperty Name)"
        )
        inf_names_str = powershell.run_cmdlet(
            cmdlet=cmd,
            force_run=True,
        )
        inf_names: List[str] = inf_names_str.strip().splitlines()
        if not inf_names:
            raise LisaException(
                "Could not resolve Hyper-V adapters that share the MAC address "
                f"'{mac_address}'"
            )

        # Get device id for all above interface names we got
        pnp_device_id_list: List[str] = []
        for name in inf_names:
            escaped_name = name.replace("'", "''")
            cmd = (
                "(Get-NetAdapter | Where-Object "
                f"{{$_.Name -eq '{escaped_name}'}} | "
                "Select-Object -First 1 -ExpandProperty PnPDeviceID)"
            )
            interface_device_id = powershell.run_cmdlet(
                cmdlet=cmd,
                force_run=True,
            )
            interface_device_id = interface_device_id.strip()
            if interface_device_id:
                pnp_device_id_list.append(interface_device_id)

        if not pnp_device_id_list:
            raise LisaException(
                "Could not resolve any PnP device IDs for the Hyper-V management "
                f"interface '{interface_name}'"
            )

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
        escaped_vm_name = vm_name.replace("'", "''")
        config_commands: List[str] = []
        for device in devices:
            escaped_instance_id = device.instance_id.replace("'", "''")
            escaped_location_path = device.location_path.replace("'", "''")
            config_commands.append(
                f"Disable-PnpDevice -InstanceId '{escaped_instance_id}' "
                "-Confirm:$false"
            )
            config_commands.append(
                f"Dismount-VMHostAssignableDevice -Force "
                f"-LocationPath '{escaped_location_path}'"
            )
            config_commands.append(
                f"Add-VMAssignableDevice -LocationPath '{escaped_location_path}' "
                f"-VMName '{escaped_vm_name}'"
            )

        powershell = self._server.tools[PowerShell]
        for cmd in config_commands:
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
