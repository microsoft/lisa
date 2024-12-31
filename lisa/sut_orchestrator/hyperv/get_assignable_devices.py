# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
# Refer: https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/deploy/deploying-graphics-devices-using-dda  # noqa E501
import re
from typing import Dict, List, Optional

from lisa.node import Node
from lisa.tools import PowerShell
from lisa.util import LisaException, find_group_in_lines, find_groups_in_lines
from lisa.util.logger import Logger

from .schema import DeviceAddressSchema


class HypervAssignableDevices:
    PKEY_DEVICE_TYPE = "{3AB22E31-8264-4b4e-9AF5-A8D2D8E33E62}  1"
    PKEY_BASE_CLASS = "{3AB22E31-8264-4b4e-9AF5-A8D2D8E33E62}  3"
    PKEY_REQUIRES_RESERVED_MEMORY_REGION = "{3AB22E31-8264-4b4e-9AF5-A8D2D8E33E62}  34"
    PKEY_ACS_COMPATIBLE_UP_HIERARCHY = "{3AB22E31-8264-4b4e-9AF5-A8D2D8E33E62}  31"
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
        return output.strip()

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

    def __get_mmio_end_address(self, start_addr: str) -> Optional[str]:
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
        end_addr_rec = None
        for rec in device_mem_addr.splitlines():
            rec = rec.strip()
            if rec.find(start_addr) >= 0:
                addr = rec.split("-")
                start_addr_rec = addr[0].split()[-1]
                end_addr_rec = addr[1].split()[0].strip()

                err = "MMIO Starting address not matching"
                assert start_addr == start_addr_rec, err
                break
        return end_addr_rec

    def __get_dda_properties(self, device_id: str) -> Optional[DeviceAddressSchema]:
        """
        Determine if a PCI device is assignable using Discrete Device Assignment (DDA)
        If so, get DDA proerprties like locationpath, device-id, friendly name
        """
        self.log.debug(f"PCI InstanceId: {device_id}")

        rmrr = self.__get_pnp_device_property(
            device_id=device_id,
            property_name=self.PKEY_REQUIRES_RESERVED_MEMORY_REGION,
        )
        rmrr = rmrr.strip()
        if rmrr != "False":
            self.log.debug(
                "BIOS requires that this device remain attached to BIOS-owned memory."
                "Not assignable."
            )
            return None

        acs_up = self.__get_pnp_device_property(
            device_id=device_id,
            property_name=self.PKEY_ACS_COMPATIBLE_UP_HIERARCHY,
        )
        acs_up = acs_up.strip()
        if acs_up == self.PROP_ACS_COMPATIBLE_UP_HIERARCHY_NOT_SUPPORTED:
            self.log.debug(
                "Traffic from this device may be redirected to other devices in "
                "the system. Not assignable."
            )
            return None

        dev_type = self.__get_pnp_device_property(
            device_id=device_id, property_name=self.PKEY_DEVICE_TYPE
        )
        dev_type = dev_type.strip()
        if dev_type == self.PROP_DEVICE_TYPE_PCI_EXPRESS_ENDPOINT:
            self.log.debug("Express Endpoint -- more secure.")
        else:
            if dev_type == (
                self.PROP_DEVICE_TYPE_PCI_EXPRESS_ROOT_COMPLEX_INTEGRATED_ENDPOINT
            ):
                self.log.debug("Embedded Endpoint -- less secure.")
            elif dev_type == self.PROP_DEVICE_TYPE_PCI_EXPRESS_LEGACY_ENDPOINT:
                dev_base_class = self.__get_pnp_device_property(
                    device_id=device_id,
                    property_name=self.PKEY_BASE_CLASS,
                )
                dev_base_class = dev_base_class.strip()
                if dev_base_class == self.PROP_BASE_CLASS_DISPLAY_CTRL:
                    self.log.debug("Legacy Express Endpoint -- graphics controller.")
                else:
                    self.log.debug("Legacy, non-VGA PCI device. Not assignable.")
                    return None
            else:
                if dev_type == self.PROP_DEVICE_TYPE_PCI_EXPRESS_TREATED_AS_PCI:
                    self.log.debug(
                        "BIOS kept control of PCI Express for this device. "
                        "Not assignable."
                    )
                else:
                    self.log.debug(
                        "Old-style PCI device, switch port, etc. " "Not assignable."
                    )
                return None

        # Get the device location path
        location_path = self.__get_pnp_device_property(
            device_id=device_id,
            property_name="DEVPKEY_Device_LocationPaths",
        )
        location_path = location_path.strip().splitlines()[0]
        self.log.debug(f"Device locationpath: {location_path}")
        assert location_path.find("PCI") == 0, "Location path is wrong"

        cmd = (
            "(Get-PnpDevice -PresentOnly -InstanceId "
            f"'{device_id}').ConfigManagerErrorCode"
        )
        conf_mng_err_code = self.pwsh.run_cmdlet(
            cmdlet=cmd,
            force_run=True,
            sudo=True,
        )
        conf_mng_err_code = conf_mng_err_code.strip()
        self.log.debug(f"ConfigManagerErrorCode: {conf_mng_err_code}")
        if conf_mng_err_code == "CM_PROB_DISABLED":
            self.log.debug(
                "Device is Disabled, unable to check resource requirements, "
                "it may be assignable."
            )
            self.log.debug("Enable the device and rerun this script to confirm.")
            return None

        irq_assignements = [
            i
            for i in self.pnp_allocated_resources
            if i["Dependent"].find(device_id.replace("\\", "\\\\")) >= 0
        ]
        if irq_assignements:
            msi_assignments = [
                i
                for i in self.pnp_allocated_resources
                if i["Antecedent"].find("IRQNumber=42949") >= 0
            ]
            if not msi_assignments:
                self.log.debug(
                    "All of the interrupts are line-based, no assignment can work."
                )
                return None
            else:
                self.log.debug("Its interrupts are message-based, assignment can work.")
        else:
            self.log.debug("It has no interrupts at all -- assignment can work.")

        mmio_assignments = [
            i
            for i in self.pnp_allocated_resources
            if i["Dependent"].find(device_id.replace("\\", "\\\\")) >= 0
            and i["__RELPATH"].find("Win32_DeviceMemoryAddres") >= 0
        ]
        mmio_total = 0
        if mmio_assignments:
            for rec in mmio_assignments:
                antecedent_val = rec["Antecedent"]
                addresses = antecedent_val.split('"')
                assert len(addresses) >= 2, "Antecedent: Can't get MMIO Start Address"
                start_address = hex(int(addresses[1].strip())).upper()
                start_address_hex = start_address.replace("X", "x")
                end_address = self.__get_mmio_end_address(start_address_hex)
                assert end_address, "Can not get MMIO End Address"

                mmio = int(end_address, 16) - int(start_address, 16)
                mmio_total += mmio
            if mmio_total:
                mmio_total = round(mmio_total / (1024 * 1024))
                self.log.debug(f"Device '{device_id}', Total MMIO = {mmio_total}MB ")
        else:
            self.log.debug("It has no MMIO space")

        device = DeviceAddressSchema()
        device.location_path = location_path
        device.instance_id = device_id
        return device
