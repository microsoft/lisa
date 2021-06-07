# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import Any, List

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import LisaException

# Example output of lspci commnd -
# lspci -m
#
# 00:00.0 "Host bridge" "Intel Corporation" "5520 I/O Hub to ESI Port" -r13
#    "Dell" "PowerEdge R610 I/O Hub to ESI Port"
# 00:1a.0 "USB controller" "Intel Corporation" "82801I (ICH9 Family) USB UHCI
#    Controller #4" -r02 "Dell" "PowerEdge R610 USB UHCI Controller"
# 0b:00.1 "Ethernet controller" "Broadcom Corporation" "NetXtreme II BCM5709 Gigabit
#    Ethernet" -r20 "Dell" "PowerEdge R610 BCM5709 Gigabit Ethernet"
#
# Segregting the ouput in 4 categories -
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


class PciDevice:
    def __init__(self, pci_device_raw: str) -> None:
        self.parse(pci_device_raw)

    def parse(self, raw_str: str) -> None:
        matched_pci_device_info = PATTERN_PCI_DEVICE.match(raw_str)
        if matched_pci_device_info:
            self.slot = matched_pci_device_info.group("slot")
            self.device_class = matched_pci_device_info.group("device_class")
            self.vendor = matched_pci_device_info.group("vendor")
            self.device_info = matched_pci_device_info.group("device")
        else:
            raise LisaException("cannot find any matched pci devices")


class Lspci(Tool):
    @property
    def command(self) -> str:
        return "lspci"

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

    def get_device_list(self, force_run: bool = False) -> List[PciDevice]:
        if (not self._pci_devices) or force_run:
            result = self.run("-m", force_run=force_run, shell=True)
            if result.exit_code != 0:
                result = self.run("-m", force_run=force_run, shell=True, sudo=True)
                if result.exit_code != 0:
                    raise LisaException(
                        f"get unexpected non-zero exit code {result.exit_code} "
                        f"when run {self.command} -m."
                    )
            for pci_raw in result.stdout.splitlines():
                pci_device = PciDevice(pci_raw)
                self._pci_devices.append(pci_device)

        return self._pci_devices
