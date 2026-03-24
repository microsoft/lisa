# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
# Refer: https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/deploy/deploying-graphics-devices-using-dda  # noqa E501
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from lisa.node import Node
from lisa.tools import PowerShell
from lisa.util import LisaException, find_group_in_lines, find_groups_in_lines
from lisa.util.logger import Logger

from .schema import DeviceAddressSchema


@dataclass
class _PciDeviceLocationRecord:
    friendly_name: str
    instance_id: str
    location_paths: List[str]
    config_manager_error_code: str = ""


class HypervAssignableDevices:
    PKEY_DEVICE_TYPE = "{3AB22E31-8264-4b4e-9AF5-A8D2D8E33E62}  1"
    PKEY_BASE_CLASS = "{3AB22E31-8264-4b4e-9AF5-A8D2D8E33E62}  3"
    PKEY_REQUIRES_RESERVED_MEMORY_REGION = "{3AB22E31-8264-4b4e-9AF5-A8D2D8E33E62}  34"
    PKEY_ACS_COMPATIBLE_UP_HIERARCHY = "{3AB22E31-8264-4b4e-9AF5-A8D2D8E33E62}  31"
    # Hyper-V reports MSI/MSI-X assignments with this synthetic IRQ marker.
    MSI_IRQ_RESOURCE_MARKER = "IRQNumber=42949"
    PROP_DEVICE_TYPE_PCI_EXPRESS_ENDPOINT = "2"
    PROP_DEVICE_TYPE_PCI_EXPRESS_LEGACY_ENDPOINT = "3"
    PROP_DEVICE_TYPE_PCI_EXPRESS_ROOT_COMPLEX_INTEGRATED_ENDPOINT = "4"
    PROP_DEVICE_TYPE_PCI_EXPRESS_TREATED_AS_PCI = "5"
    PROP_ACS_COMPATIBLE_UP_HIERARCHY_NOT_SUPPORTED = "0"
    PROP_BASE_CLASS_DISPLAY_CTRL = "3"

    def __init__(self, host_node: Node, log: Logger):
        self.host_node = host_node
        self.log = log
        self.pwsh = self.host_node.tools[PowerShell]
        self.pnp_allocated_resources: List[
            Dict[str, str]
        ] = self.__load_pnp_allocated_resources()

    def get_assignable_devices(
        self,
        vendor_id: str,
        device_id: str,
    ) -> List[DeviceAddressSchema]:
        device_id_list = self.__get_devices_by_vendor_device_id(
            vendor_id=vendor_id, device_id=device_id
        )

        devices: List[DeviceAddressSchema] = []
        for rec in device_id_list:
            device_id = rec["device_id"]
            result = self.__get_dda_properties(device_id=device_id)
            if result:
                result.friendly_name = rec["friendly_name"]
                devices.append(result)
        return devices

    def get_assignable_devices_by_location_paths(
        self,
        location_paths: List[str],
    ) -> List[DeviceAddressSchema]:
        requested_paths = {path.strip() for path in location_paths if path.strip()}
        if not requested_paths:
            return []

        output = self.__get_present_pci_devices_with_location_paths()

        devices: List[DeviceAddressSchema] = []
        matched_paths = set()
        for rec in output:
            device_id = rec.instance_id
            if not device_id:
                continue

            available_paths = rec.location_paths
            if not available_paths:
                continue

            matching_paths = requested_paths.intersection(available_paths)
            if not matching_paths:
                continue

            matched_paths.update(matching_paths)
            current_path = next(
                path for path in available_paths if path in matching_paths
            )
            result = self.__get_dda_properties(device_id=device_id)
            if not result:
                raise LisaException(
                    f"Device at location path '{current_path}' is present but "
                    "is not assignable by Hyper-V DDA"
                )

            result.location_path = current_path
            result.friendly_name = rec.friendly_name
            devices.append(result)

        missing_paths = requested_paths.difference(matched_paths)
        if missing_paths:
            raise LisaException(
                "Could not find PCI device(s) for Hyper-V location path(s): "
                f"{', '.join(sorted(missing_paths))}"
            )

        return devices

    def get_pnp_device_by_location_path(
        self,
        location_path: str,
    ) -> Optional[Dict[str, Any]]:
        normalized_path = location_path.strip()
        if not normalized_path:
            return None

        matches = [
            rec
            for rec in self.__get_present_pci_devices_with_location_paths()
            if normalized_path in rec.location_paths
        ]
        if len(matches) > 1:
            raise LisaException(
                f"Multiple PnP devices matched Hyper-V location path "
                f"'{location_path}'"
            )

        if not matches:
            return None

        match = matches[0]
        return {
            "FriendlyName": match.friendly_name,
            "InstanceId": match.instance_id,
            "ConfigManagerErrorCode": match.config_manager_error_code,
        }

    def __get_present_pci_devices_with_location_paths(
        self,
    ) -> List[_PciDeviceLocationRecord]:
        cmd = """
Get-PnpDevice -PresentOnly |
Where-Object {$_.InstanceId -like 'PCI\\*'} |
ForEach-Object {
    $instanceId = $_.InstanceId
    $locationPaths = $null
    try {
        $locationPaths = (
            Get-PnpDeviceProperty -InstanceId $instanceId
                'DEVPKEY_Device_LocationPaths' -ErrorAction Stop
        ).Data
    } catch {
        Write-Verbose (
            "Failed to read DEVPKEY_Device_LocationPaths for device '{0}': {1}" -f
                $instanceId, $_.Exception.Message
        )
    }

    $locationPath = $null
    if ($locationPaths -is [System.Array]) {
        $locationPath = $locationPaths | Select-Object -First 1
    } else {
        $locationPath = $locationPaths
    }

    [PSCustomObject]@{
        FriendlyName = $_.FriendlyName
        InstanceId = $instanceId
        LocationPath = $locationPath
        LocationPaths = $locationPaths
        ConfigManagerErrorCode = $_.ConfigManagerErrorCode
    }
}
"""
        output = self.pwsh.run_cmdlet(
            cmdlet=cmd,
            sudo=True,
            force_run=True,
            output_json=True,
        )

        if not output:
            raise LisaException("No present PCI devices were found on the Hyper-V host")

        if not isinstance(output, list):
            output = [output]

        result: List[_PciDeviceLocationRecord] = []
        for rec in output:
            if not isinstance(rec, dict):
                continue

            location_paths = self.__normalize_location_paths(
                rec.get("LocationPaths", rec.get("LocationPath"))
            )

            result.append(
                _PciDeviceLocationRecord(
                    friendly_name=str(rec.get("FriendlyName", "") or "").strip(),
                    instance_id=str(rec.get("InstanceId", "") or "").strip(),
                    location_paths=location_paths,
                    config_manager_error_code=str(
                        rec.get("ConfigManagerErrorCode", "") or ""
                    ).strip(),
                )
            )

        return result

    def __get_devices_by_vendor_device_id(
        self,
        vendor_id: str,
        device_id: str,
    ) -> List[Dict[str, str]]:
        """
        Get the device ID list for given vendor/device ID combination
        """
        devices: List[Dict[str, str]] = []
        device_regex = re.compile(
            r"Description\s+:\s*(?P<desc>.+)\n.*DeviceID\s+:\s*(?P<device_id>.+)"
        )

        cmd = (
            "Get-WmiObject Win32_PnPEntity -Filter "
            f"\"DeviceID LIKE 'PCI\\\\VEN_{vendor_id}&DEV_{device_id}%'\""
        )
        stdout = self.pwsh.run_cmdlet(
            cmdlet=cmd,
            force_run=True,
            sudo=True,
        )

        devices_str = stdout.strip().split("\r\n\r\n")
        filtered_devices = [i.strip() for i in devices_str if i.strip() != ""]
        for device_properties in filtered_devices:
            res = find_group_in_lines(
                lines=device_properties,
                pattern=device_regex,
                single_line=False,
            )
            if not res:
                raise LisaException("Can not extract DeviceId/Description")

            devices.append(
                {
                    "device_id": res["device_id"].strip(),
                    "friendly_name": res["desc"].strip(),
                }
            )
        return devices

    def __get_pnp_device_property(self, device_id: str, property_name: str) -> str:
        """
        Retrieve a PnP device property by instance ID and property key.
        """
        cmd = (
            "(Get-PnpDeviceProperty -InstanceId "
            f"'{device_id}' '{property_name}').Data"
        )

        output = self.pwsh.run_cmdlet(
            cmdlet=cmd,
            sudo=True,
            force_run=True,
        )
        return str(output.strip())

    def __normalize_location_paths(self, raw_location_paths: Any) -> List[str]:
        if raw_location_paths is None:
            return []

        if isinstance(raw_location_paths, list):
            location_paths = raw_location_paths
        else:
            location_paths = str(raw_location_paths).splitlines()

        return [
            location_path
            for location_path in (str(entry).strip() for entry in location_paths)
            if location_path
        ]

    def __load_pnp_allocated_resources(self) -> List[Dict[str, str]]:
        # Command output result (just 2 device properties)
        # ========================================================
        # __GENUS          : 2
        # __CLASS          : Win32_PNPAllocatedResource
        # __SUPERCLASS     : CIM_AllocatedResource
        # __DYNASTY        : CIM_Dependency
        # __RELPATH        : Win32_PNPAllocatedResource.Antecedent="\\\\WIN-2IDCNC2D5V
        #                   C\\root\\cimv2:Win32_DeviceMemoryAddress.StartingAddress=\
        #                   "2463203328\"",Dependent="\\\\WIN-2IDCNC2D5VC\\root\\cimv2:
        #                   Win32_PnPEntity.DeviceID=\"PCI\\\\VEN_8086&DEV_A1A3&
        #                   SUBSYS_07161028&REV_09\\\\3&11583659&0&FC\""
        # __PROPERTY_COUNT : 2
        # __DERIVATION     : {CIM_AllocatedResource, CIM_Dependency}
        # __SERVER         : WIN-2IDCNC2D5VC
        # __NAMESPACE      : root\cimv2
        # __PATH           : \\WIN-2IDCNC2D5VC\root\cimv2:Win32_PNPAllocatedResource.
        #                   Antecedent="\\\\WIN-2IDCNC2D5VC\\root\\cimv2:Win32_
        #                   DeviceMemoryAddress.StartingAddress=\"2463203328\"",
        #                   Dependent="\\\\WIN-2IDCNC2D5VC\\root\\cimv2:Win32_PnP
        #                   Entity.DeviceID=\"PCI\\\\VEN_8086&DEV_A1A3&SUBSYS_07161028&
        #                   REV_09\\\\3&11583659&0&FC\""
        # Antecedent       : \\WIN-2IDCNC2D5VC\root\cimv2:Win32_DeviceMemoryAddress.
        #                    StartingAddress="2463203328"
        # Dependent        : \\WIN-2IDCNC2D5VC\root\cimv2:Win32_PnPEntity.DeviceID=
        #                   "PCI\\VEN_8086&DEV_A1A3&SUBSYS_07161028&REV_09\\3
        #                    &11583659&0&FC"
        # PSComputerName   : WIN-2IDCNC2D5VC

        # __GENUS          : 2
        # __CLASS          : Win32_PNPAllocatedResource
        # __SUPERCLASS     : CIM_AllocatedResource
        # __DYNASTY        : CIM_Dependency
        # __RELPATH        : Win32_PNPAllocatedResource.Antecedent="\\\\WIN-2IDCNC2D5VC
        #                   \\root\\cimv2:Win32_PortResource.StartingAddress=\"8192\"",
        #                   Dependent="\\\\WIN-2IDCNC2D5VC\\root\\cimv2:Win32_PnPEntity
        #                   .DeviceID=\"PCI\\\\VEN_8086&DEV_A1A3&SUBSYS_07161028&REV_09
        #                   \\\\3&11583659&0&FC\""
        # __PROPERTY_COUNT : 2
        # __DERIVATION     : {CIM_AllocatedResource, CIM_Dependency}
        # __SERVER         : WIN-2IDCNC2D5VC
        # __NAMESPACE      : root\cimv2
        # __PATH           : \\WIN-2IDCNC2D5VC\root\cimv2:Win32_PNPAllocatedResource.
        #                    Antecedent="\\\\WIN-2IDCNC2D5VC\\root\\cimv2:Win32_PortR
        #                    esource.StartingAddress=\"8192\"",Dependent="\\\\WIN-2ID
        #                    CNC2D5VC\\root\\cimv2:Win32_PnPEntity.DeviceID=\"PCI\\\\
        #                    VEN_8086&DEV_A1A3&SUBSYS_07161028&REV_09\\\\3&11
        #                    583659&0&FC\""
        # Antecedent       : \\WIN-2IDCNC2D5VC\root\cimv2:Win32_PortResource.
        #                    StartingAddress="8192"
        # Dependent        : \\WIN-2IDCNC2D5VC\root\cimv2:Win32_PnPEntity.DeviceID=
        #                    "PCI\\VEN_8086&DEV_A1A3&SUBSYS_07161028&REV_09\\3&
        #                    11583659&0&FC"
        # PSComputerName   : WIN-2IDCNC2D5VC

        stdout = self.pwsh.run_cmdlet(
            cmdlet="gwmi -query 'select * from Win32_PnPAllocatedResource'",
            sudo=True,
            force_run=True,
        )
        pnp_allocated_resources = stdout.strip().split("\r\n\r\n")
        result: List[Dict[str, str]] = []
        # Regular expression to match the key-value pairs
        pattern = re.compile(r"(?P<key>\S+)\s*:\s*(?P<value>.*?)(?=\n\S|\Z)", re.DOTALL)

        for rec in pnp_allocated_resources:
            extract_val = {}
            matches = find_groups_in_lines(
                lines=rec.strip(),
                pattern=pattern,
                single_line=False,
            )
            if matches:
                for element in matches:
                    key = element["key"]
                    val = element["value"]
                    val = val.replace(" ", "")
                    val = val.replace("\r\n", "")
                    extract_val[key] = val
                result.append(extract_val)
        return result

    def __get_mmio_end_address(self, start_addr: int) -> Optional[str]:
        # MemoryType   Name                  Status
        # ----------   ----                  ------
        # WindowDecode 0xE1800000-0xE1BFFFFF OK
        #             0xE2000000-0xE2000FFF OK
        # WindowDecode 0xD4000000-0xD43FFFFF OK
        #             0xD4800000-0xD4800FFF OK
        #             0xFED1C000-0xFED3FFFF OK

        device_mem_addr = self.pwsh.run_cmdlet(
            cmdlet="gwmi -query 'select * from Win32_DeviceMemoryAddress'",
            sudo=True,
            force_run=True,
        )
        mmio_pattern = re.compile(r"(?P<start>0x[0-9A-Fa-f]+)-(?P<end>0x[0-9A-Fa-f]+)")
        end_addr_rec = None
        for rec in device_mem_addr.splitlines():
            rec = rec.strip()
            match = mmio_pattern.search(rec)
            if not match:
                continue

            start_addr_rec = int(match.group("start"), 16)
            if start_addr == start_addr_rec:
                end_addr_rec = match.group("end")
                break
        return end_addr_rec

    def __get_dda_properties(self, device_id: str) -> Optional[DeviceAddressSchema]:
        """
        Determine if a PCI device is assignable using Discrete Device Assignment (DDA)
        If so, get DDA proerprties like locationpath, device-id, friendly name
        """
        self.log.debug(f"PCI InstanceId: {device_id}")

        if self.__requires_reserved_memory_region(device_id):
            return None

        if not self.__has_acs_compatible_up_hierarchy(device_id):
            return None

        if not self.__is_supported_device_type(device_id):
            return None

        location_path = self.__get_location_path(device_id)
        if self.__is_device_disabled(device_id):
            return None

        allocated_resources = self.__get_allocated_resources(device_id)
        if not self.__has_assignable_interrupts(allocated_resources):
            return None

        mmio_total = self.__get_total_mmio_in_mb(device_id, allocated_resources)
        if mmio_total is None:
            self.log.debug(f"Device '{device_id}' has no MMIO space")
        elif mmio_total:
            self.log.debug(f"Device '{device_id}', Total MMIO = {mmio_total}MB ")

        device = DeviceAddressSchema()
        device.location_path = location_path
        device.instance_id = device_id
        return device

    def __requires_reserved_memory_region(self, device_id: str) -> bool:
        rmrr = self.__get_pnp_device_property(
            device_id=device_id,
            property_name=self.PKEY_REQUIRES_RESERVED_MEMORY_REGION,
        ).strip()
        if rmrr != "False":
            self.log.debug(
                "BIOS requires that this device remain attached to BIOS-owned memory."
                "Not assignable."
            )
            return True
        return False

    def __has_acs_compatible_up_hierarchy(self, device_id: str) -> bool:
        acs_up = self.__get_pnp_device_property(
            device_id=device_id,
            property_name=self.PKEY_ACS_COMPATIBLE_UP_HIERARCHY,
        ).strip()
        if acs_up == self.PROP_ACS_COMPATIBLE_UP_HIERARCHY_NOT_SUPPORTED:
            self.log.debug(
                "Traffic from this device may be redirected to other devices in "
                "the system. Not assignable."
            )
            return False
        return True

    def __is_supported_device_type(self, device_id: str) -> bool:
        dev_type = self.__get_pnp_device_property(
            device_id=device_id,
            property_name=self.PKEY_DEVICE_TYPE,
        ).strip()
        if dev_type == self.PROP_DEVICE_TYPE_PCI_EXPRESS_ENDPOINT:
            self.log.debug("Express Endpoint -- more secure.")
            return True

        if (
            dev_type
            == self.PROP_DEVICE_TYPE_PCI_EXPRESS_ROOT_COMPLEX_INTEGRATED_ENDPOINT
        ):
            self.log.debug("Embedded Endpoint -- less secure.")
            return True

        if dev_type == self.PROP_DEVICE_TYPE_PCI_EXPRESS_LEGACY_ENDPOINT:
            return self.__is_legacy_display_controller(device_id)

        if dev_type == self.PROP_DEVICE_TYPE_PCI_EXPRESS_TREATED_AS_PCI:
            self.log.debug(
                "BIOS kept control of PCI Express for this device. Not assignable."
            )
        else:
            self.log.debug("Old-style PCI device, switch port, etc. Not assignable.")
        return False

    def __is_legacy_display_controller(self, device_id: str) -> bool:
        dev_base_class = self.__get_pnp_device_property(
            device_id=device_id,
            property_name=self.PKEY_BASE_CLASS,
        ).strip()
        if dev_base_class == self.PROP_BASE_CLASS_DISPLAY_CTRL:
            self.log.debug("Legacy Express Endpoint -- graphics controller.")
            return True

        self.log.debug("Legacy, non-VGA PCI device. Not assignable.")
        return False

    def __get_location_path(self, device_id: str) -> str:
        location_path_output = self.__get_pnp_device_property(
            device_id=device_id,
            property_name="DEVPKEY_Device_LocationPaths",
        ).strip()
        location_paths = location_path_output.splitlines()
        if not location_paths:
            raise LisaException(f"Location path is empty for device '{device_id}'")

        location_path = location_paths[0]
        self.log.debug(f"Device locationpath: {location_path}")
        if not location_path.startswith("PCI"):
            raise LisaException(
                f"Location path is wrong for device '{device_id}': {location_path}"
            )
        return location_path

    def __is_device_disabled(self, device_id: str) -> bool:
        cmd = (
            "(Get-PnpDevice -PresentOnly -InstanceId "
            f"'{device_id}').ConfigManagerErrorCode"
        )
        conf_mng_err_code = self.pwsh.run_cmdlet(
            cmdlet=cmd,
            force_run=True,
            sudo=True,
        ).strip()
        self.log.debug(f"ConfigManagerErrorCode: {conf_mng_err_code}")
        if conf_mng_err_code.upper() in {"22", "CM_PROB_DISABLED"}:
            self.log.debug(
                "Device is Disabled, unable to check resource requirements, "
                "it may be assignable."
            )
            self.log.debug("Enable the device and rerun this script to confirm.")
            return True
        return False

    def __get_allocated_resources(self, device_id: str) -> List[Dict[str, str]]:
        escaped_device_id = device_id.replace("\\", "\\\\")
        return [
            resource
            for resource in self.pnp_allocated_resources
            if resource["Dependent"].find(escaped_device_id) >= 0
        ]

    def __has_assignable_interrupts(
        self,
        allocated_resources: List[Dict[str, str]],
    ) -> bool:
        if not allocated_resources:
            self.log.debug("It has no interrupts at all -- assignment can work.")
            return True

        msi_assignments = [
            resource
            for resource in allocated_resources
            if resource["Antecedent"].find(self.MSI_IRQ_RESOURCE_MARKER) >= 0
        ]
        if not msi_assignments:
            self.log.debug(
                "All of the interrupts are line-based, no assignment can work."
            )
            return False

        self.log.debug("Its interrupts are message-based, assignment can work.")
        return True

    def __get_total_mmio_in_mb(
        self,
        device_id: str,
        allocated_resources: List[Dict[str, str]],
    ) -> Optional[int]:
        mmio_assignments = [
            resource
            for resource in allocated_resources
            if resource["__RELPATH"].find("Win32_DeviceMemoryAddress") >= 0
        ]
        if not mmio_assignments:
            return None

        mmio_total = 0
        for resource in mmio_assignments:
            mmio_total += self.__get_mmio_size(device_id, resource["Antecedent"])

        return round(mmio_total / (1024 * 1024))

    def __get_mmio_size(self, device_id: str, antecedent_val: str) -> int:
        addresses = antecedent_val.split('"')
        if len(addresses) < 2:
            raise LisaException(
                "Antecedent does not contain a valid MMIO start address: "
                f"{antecedent_val}"
            )

        start_address = int(addresses[1].strip())
        end_address = self.__get_mmio_end_address(start_address)
        if not end_address:
            raise LisaException(
                "Cannot get MMIO end address for device "
                f"'{device_id}' and start address "
                f"0x{start_address:016X}"
            )

        return int(end_address, 16) - start_address
