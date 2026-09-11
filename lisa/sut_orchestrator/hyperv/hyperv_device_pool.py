# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any, Dict, List, Optional

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
    PNP_ENABLE_TIMEOUT_SECONDS = 30
    PNP_ENABLE_POLL_INTERVAL_SECONDS = 1

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
            HostDevicePoolType.PCI_NVME,
        ]
        self._server = node
        self._hyperv_runbook = runbook
        self.log = log

    def create_device_pool_from_vendor_device_id(
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
        if pool_type == HostDevicePoolType.PCI_NVME:
            if len(devices) != 1:
                raise LisaException(
                    "Hyper-V PCI NVMe vendor/device selection must resolve "
                    f"exactly one DDA-assignable device, found {len(devices)}. "
                    "Use 'location_path' to select a specific device."
                )
            self._validate_nvme_devices(devices)
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
        self._prepare_devices_on_host(location_paths)
        hv_dev = HypervAssignableDevices(
            host_node=self._server,
            log=self.log,
        )
        devices = hv_dev.get_assignable_devices_by_location_paths(location_paths)
        if pool_type == HostDevicePoolType.PCI_NVME:
            self._validate_nvme_devices(devices)
        self._append_devices_to_pool(pool_type=pool_type, devices=devices)

    def _validate_nvme_devices(self, devices: List[DeviceAddressSchema]) -> None:
        powershell = self._server.tools[PowerShell]
        for device in devices:
            escaped_instance_id = device.instance_id.replace("'", "''")
            disk_records = powershell.run_cmdlet(
                cmdlet=f"""
$controllerId = '{escaped_instance_id}'
$pending = [System.Collections.Generic.Queue[string]]::new()
$seen = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
)
$pending.Enqueue($controllerId)
while ($pending.Count -gt 0) {{
    $currentId = $pending.Dequeue()
    if (-not $seen.Add($currentId)) {{
        continue
    }}

    $childrenProperty = Get-PnpDeviceProperty `
        -InstanceId $currentId `
        -KeyName 'DEVPKEY_Device_Children' `
        -ErrorAction SilentlyContinue
    if ($currentId -eq $controllerId -and $null -eq $childrenProperty) {{
        throw "Could not query PnP children for NVMe controller '$controllerId'"
    }}
    foreach ($childId in @($childrenProperty.Data)) {{
        if ($childId) {{
            $pending.Enqueue([string]$childId)
        }}
    }}
}}

$diskDrives = @(
    Get-CimInstance Win32_DiskDrive |
    Where-Object {{ $seen.Contains([string]$_.PNPDeviceID) }}
)
$diskRecords = foreach ($diskDrive in $diskDrives) {{
    $disk = Get-Disk -Number ([int]$diskDrive.Index) -ErrorAction Stop
    $mountedPartitions = @(
        Get-CimInstance `
            -Namespace ROOT/Microsoft/Windows/Storage `
            -ClassName MSFT_Partition `
            -Filter "DiskNumber = $($disk.Number)" `
            -ErrorAction Stop |
        Where-Object {{ @($_.AccessPaths).Count -gt 0 }}
    )
    [PSCustomObject]@{{
        Number = [int]$disk.Number
        FriendlyName = [string]$disk.FriendlyName
        BusType = [string]$disk.BusType
        IsBoot = [bool]$disk.IsBoot
        IsSystem = [bool]$disk.IsSystem
        IsMounted = ($mountedPartitions.Count -gt 0)
    }}
}}
$diskRecords
""",
                output_json=True,
                force_run=True,
            )
            if disk_records is None or disk_records == "":
                normalized_records: List[Dict[str, Any]] = []
            elif isinstance(disk_records, list):
                normalized_records = disk_records
            else:
                normalized_records = [disk_records]

            if len(normalized_records) != 1 or not isinstance(
                normalized_records[0], dict
            ):
                raise LisaException(
                    f"Hyper-V PCI NVMe device '{device.instance_id}' must map "
                    "to exactly one Windows disk, found "
                    f"{len(normalized_records)}"
                )

            disk = normalized_records[0]
            required_properties = {
                "Number",
                "BusType",
                "IsBoot",
                "IsSystem",
                "IsMounted",
            }
            missing_properties = required_properties.difference(disk)
            if missing_properties:
                raise LisaException(
                    f"Hyper-V PCI NVMe device '{device.instance_id}' returned "
                    "an incomplete Windows disk safety record. Missing: "
                    f"{', '.join(sorted(missing_properties))}"
                )

            bus_type = str(disk["BusType"]).strip()
            if bus_type.lower() != "nvme":
                raise LisaException(
                    f"Hyper-V PCI NVMe device '{device.instance_id}' maps to "
                    f"Windows disk bus type '{bus_type or 'unknown'}', not NVMe"
                )

            unsafe_reasons = []
            if disk.get("IsBoot"):
                unsafe_reasons.append("boot")
            if disk.get("IsSystem"):
                unsafe_reasons.append("system")
            if disk.get("IsMounted"):
                unsafe_reasons.append("mounted")
            if unsafe_reasons:
                disk_number = disk.get("Number", "unknown")
                raise LisaException(
                    f"Hyper-V PCI NVMe device '{device.instance_id}' maps to "
                    f"unsafe Windows disk {disk_number}: "
                    f"{', '.join(unsafe_reasons)}"
                )

    def _prepare_devices_on_host(self, location_paths: List[str]) -> None:
        normalized_paths = [path.strip() for path in location_paths if path.strip()]
        if not normalized_paths:
            return

        mount_results: Dict[str, Any] = {}
        for location_path in normalized_paths:
            mount_results[location_path] = self._mount_device_on_host(location_path)

        hv_dev = HypervAssignableDevices(
            host_node=self._server,
            log=self.log,
        )
        pnp_devices_by_path = hv_dev.get_pnp_devices_by_location_paths(normalized_paths)

        for location_path in normalized_paths:
            mount_result = mount_results[location_path]
            pnp_device = pnp_devices_by_path.get(location_path)
            if mount_result.exit_code != 0:
                mount_output = mount_result.stdout.strip() or "<no output>"
                if not pnp_device:
                    raise LisaException(
                        f"Failed to mount Hyper-V assignable device at location "
                        f"path '{location_path}'. Exit code: "
                        f"{mount_result.exit_code}. Output: {mount_output}"
                    )

                self.log.debug(
                    f"Mount-VMHostAssignableDevice returned exit code "
                    f"{mount_result.exit_code} for location path "
                    f"'{location_path}', but the device is still visible on the "
                    f"host. Output: {mount_output}"
                )

            if not pnp_device:
                continue

            instance_id = pnp_device.instance_id
            config_manager_error_code = pnp_device.config_manager_error_code
            if instance_id and self._is_pnp_device_disabled(config_manager_error_code):
                self.log.info(
                    f"Enabling disabled host device '{instance_id}' for location "
                    f"path '{location_path}'"
                )
                escaped_instance_id = instance_id.replace("'", "''")
                powershell = self._server.tools[PowerShell]
                powershell.run_cmdlet(
                    cmdlet=(
                        f"Enable-PnpDevice -InstanceId '{escaped_instance_id}' "
                        "-Confirm:$false"
                    ),
                    force_run=True,
                )
                self._wait_for_pnp_device_enabled(instance_id, location_path)

    def _mount_device_on_host(self, location_path: str) -> Any:
        powershell = self._server.tools[PowerShell]

        assigned_vm_names = self._get_assigned_vm_names(location_path)
        if assigned_vm_names:
            raise ResourceAwaitableException(
                f"Hyper-V passthrough device '{location_path}' is currently "
                f"assigned to VM(s): {', '.join(sorted(assigned_vm_names))}"
            )

        escaped_location_path = location_path.replace("'", "''")
        mount_cmdlet = (
            "Mount-VMHostAssignableDevice " f"-LocationPath '{escaped_location_path}'"
        )
        mount_process = powershell.run_cmdlet_async(
            cmdlet=mount_cmdlet,
            force_run=True,
        )
        mount_result = powershell.wait_result(
            process=mount_process,
            cmdlet=mount_cmdlet,
            fail_on_error=False,
        )
        return mount_result

    def _is_pnp_device_disabled(self, config_manager_error_code: Any) -> bool:
        normalized_code = str(config_manager_error_code or "").strip().upper()
        return normalized_code in {"22", "CM_PROB_DISABLED"}

    def _wait_for_pnp_device_enabled(
        self,
        instance_id: str,
        location_path: str,
    ) -> None:
        escaped_instance_id = instance_id.replace("'", "''")
        powershell = self._server.tools[PowerShell]
        cmdlet = f"""
$instanceId = '{escaped_instance_id}'
$deadline = (Get-Date).AddSeconds({self.PNP_ENABLE_TIMEOUT_SECONDS})
do {{
    $device = Get-PnpDevice `
        -PresentOnly `
        -InstanceId $instanceId `
        -ErrorAction SilentlyContinue
    if ($null -ne $device) {{
        $code = "$($device.ConfigManagerErrorCode)".Trim()
        if ($code -notin @('22', 'CM_PROB_DISABLED')) {{
            Write-Output $code
            exit 0
        }}
    }}
    Start-Sleep -Seconds {self.PNP_ENABLE_POLL_INTERVAL_SECONDS}
}} while ((Get-Date) -lt $deadline)

$finalDevice = Get-PnpDevice `
    -PresentOnly `
    -InstanceId $instanceId `
    -ErrorAction SilentlyContinue
if ($null -eq $finalDevice) {{
    Write-Output 'device_not_present'
}} else {{
    Write-Output "$($finalDevice.ConfigManagerErrorCode)".Trim()
}}
exit 1
"""
        process = powershell.run_cmdlet_async(cmdlet=cmdlet, force_run=True)
        result = powershell.wait_result(
            process=process,
            cmdlet=cmdlet,
            fail_on_error=False,
            timeout=self.PNP_ENABLE_TIMEOUT_SECONDS + 5,
        )
        if result.exit_code != 0:
            last_state = result.stdout.strip() or "unknown"
            raise LisaException(
                f"PnP device '{instance_id}' for location path '{location_path}' "
                f"did not transition to enabled state within "
                f"{self.PNP_ENABLE_TIMEOUT_SECONDS} seconds. "
                f"Last ConfigManagerErrorCode: {last_state}"
            )

    def _get_assigned_vm_names(self, location_path: str) -> List[str]:
        escaped_location_path = location_path.replace("'", "''")
        powershell = self._server.tools[PowerShell]
        stdout = powershell.run_cmdlet(
            cmdlet=f"""
$target = '{escaped_location_path}'
Get-VM | ForEach-Object {{
    $vmName = $_.Name
    $assignedDevice = Get-VMAssignableDevice `
        -VMName $vmName `
        -LocationPath $target `
        -ErrorAction SilentlyContinue
    if ($assignedDevice) {{
        Write-Output $vmName
    }}
}}
""",
            force_run=True,
        )
        return [line.strip() for line in stdout.splitlines() if line.strip()]

    def _append_devices_to_pool(
        self,
        pool_type: HostDevicePoolType,
        devices: List[DeviceAddressSchema],
    ) -> None:
        primary_nic_id_list = (
            []
            if pool_type == HostDevicePoolType.PCI_NVME
            else self.get_primary_nic_id()
        )
        pool = self.available_host_devices.get(pool_type, [])
        known_instance_ids = {device.instance_id for device in pool}
        for dev in devices:
            if dev.instance_id in primary_nic_id_list:
                continue

            if dev.instance_id in known_instance_ids:
                continue

            pool.append(dev)
            known_instance_ids.add(dev.instance_id)
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

    def _return_devices_to_pool(
        self,
        pool_type: HostDevicePoolType,
        devices: List[DeviceAddressSchema],
    ) -> None:
        pool = self.available_host_devices.get(pool_type, [])
        for device in devices:
            if device not in pool:
                pool.append(device)
        self.available_host_devices[pool_type] = pool

    def release_devices(
        self,
        node_context: NodeContext,
    ) -> None:
        vm_name = node_context.vm_name
        devices_ctx = node_context.passthrough_devices
        escaped_vm_name = vm_name.replace("'", "''")
        for ctx in devices_ctx:
            for device in ctx.device_list:
                escaped_location_path = device.location_path.replace("'", "''")
                escaped_instance_id = device.instance_id.replace("'", "''")
                powershell = self._server.tools[PowerShell]
                powershell.run_cmdlet(
                    f"Remove-VMAssignableDevice "
                    f"-LocationPath '{escaped_location_path}' "
                    f"-VMName '{escaped_vm_name}'",
                    force_run=True,
                )
                powershell.run_cmdlet(
                    f"Mount-VMHostAssignableDevice -LocationPath "
                    f"'{escaped_location_path}'",
                    force_run=True,
                )
                powershell.run_cmdlet(
                    f"Enable-PnpDevice -InstanceId '{escaped_instance_id}' "
                    "-Confirm:$false",
                    force_run=True,
                )
                self._wait_for_pnp_device_enabled(
                    device.instance_id,
                    device.location_path,
                )

        for ctx in devices_ctx:
            self._return_devices_to_pool(ctx.pool_type, ctx.device_list)
        node_context.passthrough_devices.clear()

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
        if not device_configs:
            return

        for pool_type in {config.type for config in device_configs}:
            self.available_host_devices[pool_type] = []

        super().configure_device_passthrough_pool(
            device_configs=device_configs,
        )

    def _assign_devices_to_vm(
        self,
        vm_name: str,
        pool_type: HostDevicePoolType,
        devices: List[DeviceAddressSchema],
    ) -> None:
        # Assign the devices to the VM
        escaped_vm_name = vm_name.replace("'", "''")
        disabled_devices: List[DeviceAddressSchema] = []
        dismounted_devices: List[DeviceAddressSchema] = []
        assigned_devices: List[DeviceAddressSchema] = []
        powershell = self._server.tools[PowerShell]

        try:
            if pool_type == HostDevicePoolType.PCI_NVME:
                self._validate_nvme_devices(devices)

            for device in devices:
                escaped_instance_id = device.instance_id.replace("'", "''")
                escaped_location_path = device.location_path.replace("'", "''")
                powershell.run_cmdlet(
                    cmdlet=(
                        f"Disable-PnpDevice -InstanceId '{escaped_instance_id}' "
                        "-Confirm:$false"
                    ),
                    force_run=True,
                )
                disabled_devices.append(device)

                powershell.run_cmdlet(
                    cmdlet=(
                        f"Dismount-VMHostAssignableDevice -Force "
                        f"-LocationPath '{escaped_location_path}'"
                    ),
                    force_run=True,
                )
                dismounted_devices.append(device)

                powershell.run_cmdlet(
                    cmdlet=(
                        f"Add-VMAssignableDevice "
                        f"-LocationPath '{escaped_location_path}' "
                        f"-VMName '{escaped_vm_name}'"
                    ),
                    force_run=True,
                )
                assigned_devices.append(device)
        except LisaException as err:
            rollback_errors = self._rollback_dda_assignment(
                vm_name=vm_name,
                disabled_devices=disabled_devices,
                dismounted_devices=dismounted_devices,
                assigned_devices=assigned_devices,
            )
            if rollback_errors:
                raise LisaException(
                    "Failed to assign Hyper-V DDA device(s) to VM "
                    f"'{vm_name}': {err}. Rollback also failed: "
                    f"{'; '.join(rollback_errors)}"
                ) from err
            self._return_devices_to_pool(pool_type, devices)
            raise

    def _rollback_dda_assignment(
        self,
        vm_name: str,
        disabled_devices: List[DeviceAddressSchema],
        dismounted_devices: List[DeviceAddressSchema],
        assigned_devices: List[DeviceAddressSchema],
    ) -> List[str]:
        powershell = self._server.tools[PowerShell]
        escaped_vm_name = vm_name.replace("'", "''")
        rollback_errors: List[str] = []

        self.log.info(f"Rolling back Hyper-V DDA assignment for VM '{vm_name}'")

        for device in reversed(assigned_devices):
            escaped_location_path = device.location_path.replace("'", "''")
            error = self._run_dda_rollback_cmdlet(
                powershell=powershell,
                description=(
                    f"Remove DDA device '{device.location_path}' from VM '{vm_name}'"
                ),
                cmdlet=(
                    f"Remove-VMAssignableDevice "
                    f"-LocationPath '{escaped_location_path}' "
                    f"-VMName '{escaped_vm_name}'"
                ),
            )
            if error:
                rollback_errors.append(error)

        for device in reversed(dismounted_devices):
            escaped_location_path = device.location_path.replace("'", "''")
            error = self._run_dda_rollback_cmdlet(
                powershell=powershell,
                description=f"Mount DDA device '{device.location_path}' on host",
                cmdlet=(
                    f"Mount-VMHostAssignableDevice "
                    f"-LocationPath '{escaped_location_path}'"
                ),
            )
            if error:
                rollback_errors.append(error)

        for device in reversed(disabled_devices):
            escaped_instance_id = device.instance_id.replace("'", "''")
            error = self._run_dda_rollback_cmdlet(
                powershell=powershell,
                description=(
                    f"Enable PnP device '{device.instance_id}' for location path "
                    f"'{device.location_path}'"
                ),
                cmdlet=(
                    f"Enable-PnpDevice -InstanceId '{escaped_instance_id}' "
                    "-Confirm:$false"
                ),
            )
            if error:
                rollback_errors.append(error)
                continue

            try:
                self._wait_for_pnp_device_enabled(
                    device.instance_id,
                    device.location_path,
                )
            except LisaException as err:
                rollback_errors.append(
                    f"PnP device '{device.instance_id}' for location path "
                    f"'{device.location_path}' was not enabled during rollback: "
                    f"{err}"
                )

        for error in rollback_errors:
            self.log.warning(error)

        return rollback_errors

    def _run_dda_rollback_cmdlet(
        self,
        powershell: PowerShell,
        description: str,
        cmdlet: str,
    ) -> Optional[str]:
        self.log.info(description)
        try:
            powershell.run_cmdlet(
                cmdlet=cmdlet,
                force_run=True,
            )
        except LisaException as err:
            return f"{description} failed: {err}"

        return None

    def _set_device_passthrough_node_context(
        self,
        node_context: NodeContext,
        node_runbook: HypervNodeSchema,
        hv: HyperV,
        vm_name: str,
    ) -> None:
        if not node_runbook.device_passthrough:
            return
        for config in node_runbook.device_passthrough:
            if config.count <= 0:
                raise LisaException(
                    "Hyper-V device_passthrough count must be greater than 0 "
                    f"for pool type '{config.pool_type.value}'. Set "
                    "device_passthrough.count to a positive value in the runbook."
                )

        hv.enable_device_passthrough(name=vm_name)

        for config in node_runbook.device_passthrough:
            devices = self.request_devices(
                pool_type=config.pool_type,
                count=config.count,
            )
            self._assign_devices_to_vm(
                vm_name=vm_name,
                pool_type=config.pool_type,
                devices=devices,
            )
            device_context = DevicePassthroughContext()
            device_context.pool_type = config.pool_type
            device_context.requested_count = config.count
            device_context.device_list = devices
            node_context.passthrough_devices.append(device_context)
