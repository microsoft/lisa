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
    find_groups_in_lines,
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

# With -mnn option, result would be with vendor/device id
# d8:00.0 "Ethernet controller [0200]" "Mellanox Technologies [15b3]"
#   "MT27520 Family [ConnectX-3 Pro] [1007]" "Mellanox Technologies [15b3]"
#   "Mellanox Technologies ConnectX-3 Pro Stand-up dual-port 40GbE MCX314A-BCCT [0006]"
PATTERN_DEVICE_ID = re.compile(r"\[(?P<id>[^\]]{4})\]")


DEVICE_TYPE_DICT: Dict[str, List[str]] = {
    constants.DEVICE_TYPE_SRIOV: ["Ethernet controller"],
    constants.DEVICE_TYPE_NVME: ["Non-Volatile memory controller"],
    constants.DEVICE_TYPE_GPU: ["3D controller", "VGA compatible controller"],
}

VENDOR_TYPE_DICT: Dict[str, List[str]] = {
    constants.DEVICE_TYPE_GPU: ["NVIDIA Corporation"],
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
            f"device_id: {self.device_id}"
        )

    def parse(self, raw_str: str) -> None:
        matched_pci_device_info_list = find_groups_in_lines(
            lines=raw_str,
            pattern=PATTERN_PCI_DEVICE,
        )
        if matched_pci_device_info_list:
            matched_pci_device_info = matched_pci_device_info_list[0]
            self.slot = matched_pci_device_info.get("slot", "").strip()
            assert self.slot, f"Can not find slot info for: {raw_str}"

            device_class = matched_pci_device_info.get("device_class", "")
            assert device_class, f"Can not find device class for: {raw_str}"
            self.device_class = PATTERN_DEVICE_ID.sub("", device_class).strip()

            vendor = matched_pci_device_info.get("vendor", "")
            assert vendor, f"Can not find vendor info for: {raw_str}"
            vendor_id_raw = find_group_in_lines(
                lines=vendor,
                pattern=PATTERN_DEVICE_ID,
                single_line=False,
            )
            self.vendor_id = vendor_id_raw.get("id", "")
            assert self.vendor_id, f"cannot find vendor id from {raw_str}"
            self.vendor = PATTERN_DEVICE_ID.sub("", vendor).strip()

            self.device_info = matched_pci_device_info.get("device", "")
            assert self.device_info, f"Can not find device info for: {raw_str}"
            device_id_raw = find_group_in_lines(
                lines=self.device_info,
                pattern=PATTERN_DEVICE_ID,
                single_line=False,
            )
            self.device_id = device_id_raw.get("id", "")
            assert self.device_id, f"cannot find device id from {raw_str}"
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

    def get_device_names_by_type(
        self, device_type: str, force_run: bool = False
    ) -> List[str]:
        if device_type.upper() not in DEVICE_TYPE_DICT.keys():
            raise LisaException(f"pci_type '{device_type}' is not recognized.")
        class_names = DEVICE_TYPE_DICT[device_type.upper()]
        devices_list = self.get_devices(force_run)
        devices_slots = [x.slot for x in devices_list if x.device_class in class_names]
        return devices_slots

    def get_devices_by_type(
        self, device_type: str, force_run: bool = False
    ) -> List[PciDevice]:
        if device_type.upper() not in DEVICE_TYPE_DICT.keys():
            raise LisaException(
                f"pci_type '{device_type}' is not supported to be searched."
            )
        class_names = DEVICE_TYPE_DICT[device_type.upper()]
        devices_list = self.get_devices(force_run)
        device_type_list = [x for x in devices_list if x.device_class in class_names]
        return device_type_list

    def get_devices(self, force_run: bool = False) -> List[PciDevice]:
        if (not self._pci_devices) or force_run:
            self._pci_devices = []
            # Ensure pci device ids and name mappings are updated.
            self.node.execute("update-pciids", sudo=True, shell=True)
            result = self.run(
                "-Dmnn",
                force_run=force_run,
                shell=True,
                expected_exit_code=0,
                sudo=True,
            )
            for pci_raw in result.stdout.splitlines():
                pci_device = PciDevice(pci_raw)
                self._pci_devices.append(pci_device)

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
