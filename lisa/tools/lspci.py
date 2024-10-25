# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import Any, Dict, List, Optional, Pattern, Set, Type

from retry import retry

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools import Echo
from lisa.util import (
    LisaException,
    constants,
    find_group_in_lines,
    find_patterns_in_lines,
    get_matched_str,
)

# Example output of lspci command -
# lspci -m
#
# 00:00.0 "Host bridge" "Intel Corporation" "5520 I/O Hub to ESI Port" -r13
#    "Dell" "PowerEdge R610 I/O Hub to ESI Port"
# 00:1a.0 "USB controller" "Intel Corporation" "82801I (ICH9 Family) USB UHCI
#    Controller #4" -r02 "Dell" "PowerEdge R610 USB UHCI Controller"
# 0b:00.1 "Ethernet controller" "Broadcom Corporation" "NetXtreme II BCM5709 Gigabit
#    Ethernet" -r20 "Dell" "PowerEdge R610 BCM5709 Gigabit Ethernet"
# 00:08.0 "VGA compatible controller" "Microsoft Corporation"
#    "Hyper-V virtual VGA" "" ""
# 0001:00:00.0 "VGA compatible controller" "NVIDIA Corporation"
#    "GM204GL [Tesla M60]" -ra1 "NVIDIA Corporation" "GM204GL [Tesla M60]"
#
# Segregting the output in 4 categories -
# Slot - 0b:00.1
# Device Class - Ethernet controller
# Vendor - Broadcom Corporation
# Device - NetXtreme II BCM5709 Gigabit Ethernet"
#             -r20 "Dell" "PowerEdge R610 BCM5709 Gigabit Ethernet
PATTERN_PCI_DEVICE = re.compile(
    r"^(?P<slot>[^\s]+)\s+[\"\'](?P<device_class>[^\"\']+)[\"\']\s+[\"\']"
    r"(?P<vendor>[^\"\']+)[\"\']\s+[\"\'](?P<device>.*?)[\"\']?$",
    re.MULTILINE,
)

# lspci -n
# 19e3:00:00.0 0108: 1414:b111 (rev 01)
# 2b5c:00:00.0 0108: 1414:b111 (rev 01)
# d2e9:00:00.0 0108: 1414:00a9
# d3f4:00:02.0 0200: 15b3:101a (rev 80)
PATTERN_PCI_DEVICE_ID = re.compile(
    r"^(?P<slot>[^\s]+)\s+(?P<controller_id>[0-9a-fA-F]{4}):\s+"
    r"(?P<vendor_id>[0-9a-fA-F]{4}):(?P<device_id>[0-9a-fA-F]{4})",
    re.MULTILINE,
)

DEVICE_TYPE_DICT: Dict[str, List[str]] = {
    constants.DEVICE_TYPE_SRIOV: ["Ethernet controller"],
    constants.DEVICE_TYPE_NVME: ["Non-Volatile memory controller"],
    constants.DEVICE_TYPE_GPU: ["3D controller", "VGA compatible controller"],
}

VENDOR_TYPE_DICT: Dict[str, List[str]] = {
    constants.DEVICE_TYPE_GPU: ["NVIDIA Corporation"],
}

# PCI vendor ids
VENDOR_ID_AMD = "1002"  # Advanced Micro Devices, Inc. [AMD/ATI]
VENDOR_ID_INTEL = "8086"  # Intel Corporation
VENDOR_ID_MELLANOX = "15b3"  # Mellanox Technologies
VENDOR_ID_MICROSOFT = "1414"  # Microsoft Corporation
VENDOR_ID_NVIDIA = "10de"  # NVIDIA Corporation

DEVICE_ID_DICT: Dict[str, List[str]] = {
    constants.DEVICE_TYPE_SRIOV: [
        "1004",  # Mellanox Technologies MT27500/MT27520 Family [ConnectX-3/ConnectX-3 Pro Virtual Function] # noqa: E501
        "1016",  # Mellanox Technologies MT27710 Family [ConnectX-4 Lx Virtual Function]
        "1018",  # Mellanox Technologies MT27800 Family [ConnectX-5 Virtual Function]
        "101a",  # Mellanox Technologies MT28800 Family [ConnectX-5 Ex Virtual Function]
        "101e",  # Mellanox Technologies [ConnectX Family mlx5Gen Virtual Function]
        "00ba",  # Microsft Azure Network Adapter VF (MANA VF)
    ],
    constants.DEVICE_TYPE_NVME: [
        "b111"  # Microsoft Corporation Device, Local NVMe discs
    ],
    constants.DEVICE_TYPE_ASAP: [
        "00a9"  # Remote discs connected using NVMe disc controller
    ],
    constants.DEVICE_TYPE_GPU: [
        "1db4",  # NVIDIA Corporation GV100GL [Tesla V100 PCIe 16GB]
        "1eb8",  # NVIDIA Corporation TU104GL [Tesla T4]
        "13f2",  # NVIDIA Corporation GM204GL [Tesla M60]
        "74b5",  # Advanced Micro Devices, Inc. [AMD/ATI]
        "5353",  # Hyper-V virtual VGA [VGA compatible controller]
    ],
}

VENDOR_ID_DICT: Dict[str, List[str]] = {
    constants.DEVICE_TYPE_SRIOV: [
        VENDOR_ID_MICROSOFT,
        VENDOR_ID_MELLANOX,
    ],
    constants.DEVICE_TYPE_NVME: [VENDOR_ID_MICROSOFT],
    constants.DEVICE_TYPE_GPU: [VENDOR_ID_NVIDIA],
    constants.DEVICE_TYPE_AMD_GPU: [VENDOR_ID_AMD],
}

CONTROLLER_ID_DICT: Dict[str, List[str]] = {
    constants.DEVICE_TYPE_SRIOV: [
        "0200",  # Ethernet controller
        "0207",  # Infiniband controller
    ],
    constants.DEVICE_TYPE_NVME: [
        "0108",  # Non-Volatile memory controller
    ],
    constants.DEVICE_TYPE_GPU: [
        "0302",  # VGA compatible controller (NVIDIA Corporation)
        "0300",  # VGA compatible controller (Hyper-V virtual VGA)
        "1200",  # Processing accelerators (AMD GPU)
    ],
}

# Kernel driver in use: mlx4_core
# Kernel driver in use: mlx5_core
# Kernel driver in use: mlx4_core\r
# Kernel driver in use: mlx5_core\r
PATTERN_MODULE_IN_USE = re.compile(r"Kernel driver in use: ([A-Za-z0-9_-]*)", re.M)


class PciDevice:
    def __init__(self, pci_device_raw: str) -> None:
        self.parse(pci_device_raw)

    def __str__(self) -> str:
        return (
            f"PCI device: {self.slot}, "
            f"class: {self.device_class}, "
            f"vendor: {self.vendor}, "
            f"info: {self.device_info}, "
            f"vendor_id: {self.vendor_id}, "
            f"device_id: {self.device_id}, "
            f"controller_id: {self.controller_id} "
        )

    def parse(self, raw_str: str) -> None:
        matched_pci_device_info = find_group_in_lines(raw_str, PATTERN_PCI_DEVICE)

        if matched_pci_device_info:
            self.slot = matched_pci_device_info["slot"]
            assert self.slot, f"Can not find slot info for: {raw_str}"
            self.device_class = matched_pci_device_info["device_class"]
            assert self.device_class, f"Can not find device class for: {raw_str}"
            self.vendor = matched_pci_device_info["vendor"]
            assert self.vendor, f"Can not find vendor info for: {raw_str}"
            self.device_info = matched_pci_device_info["device"]
            assert self.device_info, f"Can not find device info for: {raw_str}"
            # Initialize the device_id, vendor_id and controller_id to None
            self.vendor_id = ""
            self.device_id = ""
            self.controller_id = ""
        else:
            raise LisaException("cannot find any matched pci devices")


class Lspci(Tool):
    @property
    def command(self) -> str:
        return "lspci"

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return LspciBSD

    @property
    def can_install(self) -> bool:
        return True

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command = "lspci"
        self._pci_devices: List[PciDevice] = []

    def _install(self) -> bool:
        if isinstance(self.node.os, Posix):
            self.node.os.install_packages("pciutils")
        return self._check_exists()

    # Returns device slots for given device type based on device ids.
    # Usecase: If two device types are using same controller type, this method can get
    # the device slots only for the given device type.
    # Example: To get local NVMe devices by ignoring ASAP devices which uses same nvme
    # driver and the NVMe controller id.
    # Best practice: Use this method only for usecases like above. For other usecases,
    # use 'get_device_names_by_type' method. As its difficult to maintain the list of
    # device ids for each device type. For example, the list of device ids for SRIOV and
    # GPU devices needs continuous update.
    def get_device_names_by_device_id(
        self, device_type: str, force_run: bool = False
    ) -> List[str]:
        if device_type.upper() not in DEVICE_ID_DICT.keys():
            raise LisaException(f"pci_type '{device_type}' is not recognized.")
        devices_list = self.get_devices(force_run)
        devices_slots = []

        for device in devices_list:
            if device.device_id in DEVICE_ID_DICT[device_type.upper()]:
                devices_slots.append(device.slot)
        return devices_slots

    # Returns device slot ids for given device type based on controller ids.
    # This method cannot distinguish between different device types which uses same
    # controller id. For example, NVME and ASAP devices use same controller id for.
    # In such cases, use 'get_device_names_by_device_id' method.
    def get_device_names_by_type(
        self, device_type: str, force_run: bool = False
    ) -> List[str]:
        # NVME devices are searched based on device ids as 'ASAP' devices use same
        # controller id.
        if device_type.upper() in [constants.DEVICE_TYPE_NVME]:
            return self.get_device_names_by_device_id(device_type, force_run)
        if device_type.upper() not in CONTROLLER_ID_DICT.keys():
            raise LisaException(f"pci_type '{device_type}' is not recognized.")
        devices_list = self.get_devices(force_run)
        devices_slots = []

        for device in devices_list:
            if device.controller_id in CONTROLLER_ID_DICT[device_type.upper()]:
                devices_slots.append(device.slot)
        return devices_slots

    # Returns list of pci devices for given device type based on device ids.
    # Usecases and bestpractices are same as 'get_device_names_by_device_id' method.
    def get_devices_by_device_id(
        self, device_type: str, force_run: bool = False
    ) -> List[PciDevice]:
        if device_type.upper() not in DEVICE_ID_DICT.keys():
            raise LisaException(
                f"pci_type '{device_type}' is not supported to be searched."
            )
        devices_list = self.get_devices(force_run)
        device_type_list = []
        for device in devices_list:
            if device.device_id in DEVICE_ID_DICT[device_type.upper()]:
                device_type_list.append(device)

        return device_type_list

    # Returns list of pci devices for given device type based on controller ids.
    def get_devices_by_type(
        self, device_type: str, force_run: bool = False
    ) -> List[PciDevice]:
        # NVME devices are searched based on device ids as 'ASAP' devices use same
        # controller id.
        if device_type.upper() in [constants.DEVICE_TYPE_NVME]:
            return self.get_devices_by_device_id(device_type, force_run)
        if device_type.upper() not in CONTROLLER_ID_DICT.keys():
            raise LisaException(
                f"pci_type '{device_type}' is not supported to be searched."
            )
        devices_list = self.get_devices(force_run)
        device_type_list = []
        for device in devices_list:
            if device.controller_id in CONTROLLER_ID_DICT[device_type.upper()]:
                device_type_list.append(device)

        return device_type_list

    # Retry decorator is used to handle the case where the device list is not same from
    # 'lspci -n' output and 'lspci -m' outputs.
    # It usually happens when the VM is just finished booting and not
    # all PCI devices are detected. For example SRIOV devices.
    # In such cases we need to retry after a short delay.
    @retry(KeyError, tries=30, delay=2)
    def get_devices(self, force_run: bool = False) -> List[PciDevice]:
        if (not self._pci_devices) or force_run:
            self._pci_devices = []
            self._pci_ids = {}
            # Ensure pci device ids and name mappings are updated.
            self.node.execute("update-pciids", sudo=True, shell=True)

            # Fetching the id information using 'lspci -nnm' is not reliable
            # due to inconsistencies in device id patterns.
            # Example output of 'lspci -nnm':
            # d2e9:00:00.0 "Non-Volatile memory controller [0108]" "Microsoft Corporation [1414]" "Device [00a9]" -p02 "Microsoft Corporation [1414]" "Device [0000]" # noqa: E501
            # d3f4:00:02.0 "Ethernet controller [0200]" "Mellanox Technologies [15b3]" "MT28800 Family [ConnectX-5 Ex Virtual Function] [101a]" -r80 "Mellanox Technologies [15b3]" "MT28800 Family [ConnectX-5 Ex Virtual Function] [0127]" # noqa: E501
            # Sample 'lspci -nD' output for above devices:
            # d2e9:00:00.0 0108: 1414:00a9
            # d3f4:00:02.0 0200: 15b3:101a (rev 80)
            # Fetch pci ids using 'lspci -nD':
            result = self.run(
                "-nD",
                force_run=force_run,
                shell=True,
                expected_exit_code=0,
                sudo=True,
            )
            for pci_raw in result.stdout.splitlines():
                pci_device_id_info = {}
                matched_pci_device_info = PATTERN_PCI_DEVICE_ID.match(pci_raw)
                if matched_pci_device_info:
                    pci_device_id_info[matched_pci_device_info.group("slot")] = {
                        "device_id": matched_pci_device_info.group("device_id"),
                        "vendor_id": matched_pci_device_info.group("vendor_id"),
                        "controller_id": matched_pci_device_info.group("controller_id"),
                    }
                self._pci_ids.update(pci_device_id_info)

            # Fetching the device information using 'lspci -mD':
            result = self.run(
                "-mD",
                force_run=force_run,
                shell=True,
                expected_exit_code=0,
                sudo=True,
            )
            for pci_raw in result.stdout.splitlines():
                pci_device = PciDevice(pci_raw)
                self._pci_devices.append(pci_device)

            for i in range(len(self._pci_devices)):
                pci_slot_id = self._pci_devices[i].slot
                # Raise exception if the device id is not found.
                # The retry decorator will retry after a short delay.
                if pci_slot_id not in self._pci_ids:
                    raise KeyError(f"cannot find device id from {pci_slot_id}")
                self._pci_devices[i].device_id = self._pci_ids[pci_slot_id]["device_id"]
                self._pci_devices[i].vendor_id = self._pci_ids[pci_slot_id]["vendor_id"]
                self._pci_devices[i].controller_id = self._pci_ids[pci_slot_id][
                    "controller_id"
                ]

        return self._pci_devices

    def disable_devices_by_type(self, device_type: str) -> int:
        devices = self.get_devices_by_type(device_type, force_run=True)
        if 0 == len(devices):
            raise LisaException(f"No matched device type {device_type} found.")
        for device in devices:
            self.disable_device(device=device)
        return len(devices)

    def disable_device(self, device: PciDevice) -> None:
        echo = self.node.tools[Echo]
        echo.write_to_file(
            "1",
            self.node.get_pure_path(f"/sys/bus/pci/devices/{device.slot}/remove"),
            sudo=True,
        )

        devices = self.get_devices(True)
        if any(x for x in devices if x.slot == device.slot):
            raise LisaException(f"Fail to disable {device} devices.")

    def enable_devices(self) -> None:
        self.node.tools[Echo].write_to_file(
            "1", self.node.get_pure_path("/sys/bus/pci/rescan"), sudo=True
        )

    def get_used_module(self, slot: str) -> str:
        result = self.run(
            f"-nks {slot}",
            force_run=True,
            shell=True,
            expected_exit_code=0,
        )
        matched = get_matched_str(result.stdout, PATTERN_MODULE_IN_USE)
        return matched

    def get_gpu_devices(self, force_run: bool = False) -> List[PciDevice]:
        class_names = DEVICE_TYPE_DICT[constants.DEVICE_TYPE_GPU]
        vendor_names = VENDOR_TYPE_DICT[constants.DEVICE_TYPE_GPU]
        devices_list = self.get_devices(force_run)
        gpu_device_list = [
            x
            for x in devices_list
            if x.device_class in class_names and x.vendor in vendor_names
        ]
        return gpu_device_list

    def get_devices_by_vendor_device_id(
        self,
        vendor_id: str,
        device_id: str,
        force_run: bool = False,
    ) -> List[PciDevice]:
        full_list = self.get_devices(force_run=force_run)
        devices_list = []
        for device in full_list:
            if device.device_id == device_id and device.vendor_id == vendor_id:
                devices_list.append(device)
        return devices_list


class LspciBSD(Lspci):
    _DEVICE_DRIVER_MAPPING: Dict[str, Pattern[str]] = {
        constants.DEVICE_TYPE_SRIOV: re.compile(r"mlx\d+_core\d+"),
        constants.DEVICE_TYPE_NVME: re.compile(r"nvme\d+"),
    }

    _disabled_devices: Set[str] = set()

    def get_device_names_by_type(
        self, device_type: str, force_run: bool = False
    ) -> List[str]:
        output = self.node.execute("pciconf -l", sudo=True).stdout
        if device_type.upper() not in self._DEVICE_DRIVER_MAPPING.keys():
            raise LisaException(f"pci_type '{device_type}' is not recognized.")

        class_names = self._DEVICE_DRIVER_MAPPING[device_type.upper()]
        matched = find_patterns_in_lines(
            output,
            [class_names],
        )
        return matched[0]

    @retry(tries=15, delay=3, backoff=1.15)
    def _enable_device(self, device: str) -> None:
        self.node.execute(
            f"devctl enable {device}",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"Fail to enable {device} devices.",
        )

    @retry(tries=15, delay=3, backoff=1.15)
    def _disable_device(self, device: str) -> None:
        if device in self._disabled_devices:
            return

        # devctl disable will fail if the device is already disabled.
        self.node.execute(
            f"devctl disable {device}",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"Fail to disable {device} devices.",
        )

    def enable_devices(self) -> None:
        for device in self._disabled_devices:
            self._enable_device(device)
        self._disabled_devices.clear()

    def disable_devices_by_type(self, device_type: str) -> int:
        devices = self.get_device_names_by_type(device_type, force_run=True)
        for device in devices:
            self._disable_device(device)
            self._disabled_devices.add(device)

        return len(devices)
