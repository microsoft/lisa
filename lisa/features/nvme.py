# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import List

from lisa.feature import Feature
from lisa.tools import Lspci, Nvmecli
from lisa.tools.lspci import PciDevice

FEATURE_NAME_NVME = "NVME"


class Nvme(Feature):
    # crw------- 1 root root 251, 0 Jun 21 03:08 /dev/nvme0
    _device_pattern = re.compile(r".*(?P<device_name>/dev/nvme[0-9]$)", re.MULTILINE)
    # brw-rw---- 1 root disk 259, 0 Jun 21 03:08 /dev/nvme0n1
    _namespace_pattern = re.compile(
        r".*(?P<namespace>/dev/nvme[0-9]n[0-9]$)", re.MULTILINE
    )
    # '/dev/nvme0n1          351f1f720e5a00000001 Microsoft NVMe Direct Disk               1           0.00   B /   1.92  TB    512   B +  0 B   NVMDV001' # noqa: E501
    _namespace_cli_pattern = re.compile(
        r"(?P<namespace>/dev/nvme[0-9]n[0-9])", re.MULTILINE
    )
    _pci_device_name = "Non-Volatile memory controller"
    _ls_devices: str = ""

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_NVME

    @classmethod
    def enabled(cls) -> bool:
        return True

    @classmethod
    def can_disable(cls) -> bool:
        return True

    def get_devices(self) -> List[str]:
        devices_list = []
        self._get_device_from_ls()
        for row in self._ls_devices.splitlines():
            matched_result = self._device_pattern.match(row)
            if matched_result:
                devices_list.append(matched_result.group("device_name"))
        return devices_list

    def get_namespaces(self) -> List[str]:
        namespaces = []
        self._get_device_from_ls()
        for row in self._ls_devices.splitlines():
            matched_result = self._namespace_pattern.match(row)
            if matched_result:
                namespaces.append(matched_result.group("namespace"))
        return namespaces

    def get_namespaces_from_cli(self) -> List[str]:
        namespaces_cli = []
        nvme_cli = self._node.tools[Nvmecli]
        nvme_list = nvme_cli.run("list", shell=True, sudo=True)
        for row in nvme_list.stdout.splitlines():
            matched_result = self._namespace_cli_pattern.match(row)
            if matched_result:
                namespaces_cli.append(matched_result.group("namespace"))
        return namespaces_cli

    def get_devices_from_lspci(self) -> List[PciDevice]:
        devices_from_lspci = []
        lspci_tool = self._node.tools[Lspci]
        device_list = lspci_tool.get_device_list()
        devices_from_lspci = [
            x for x in device_list if self._pci_device_name == x.device_class
        ]
        return devices_from_lspci

    def _get_device_from_ls(self, force_run: bool = False) -> None:
        if (not self._ls_devices) or force_run:
            execute_results = self._node.execute(
                "ls -l /dev/nvme*", shell=True, sudo=True
            )
            self._ls_devices = execute_results.stdout
