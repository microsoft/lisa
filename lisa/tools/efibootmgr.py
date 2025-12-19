# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import Dict

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import LisaException


class EfiBootMgr(Tool):
    # Regular expression to parse boot entries with kernel versions
    # Matches entries like: Boot0002* Ubuntu with kernel 6.8.0-1044-azure-fde
    _boot_entry_pattern = re.compile(
        r"Boot(?P<boot_num>\d+)\*?\s+(?P<boot_name>.*?)\s+with\s+kernel\s+"
        r"(?P<kernel_version>[\d\.\-\w]+)"
    )

    @property
    def command(self) -> str:
        return "efibootmgr"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        if isinstance(self.node.os, Posix):
            self.node.os.install_packages("efibootmgr")
        return self._check_exists()

    def get_boot_entries_by_kernel(self) -> Dict[str, str]:
        """
        Parse efibootmgr output and return boot entries with kernel versions as keys.

        Returns:
            Dict mapping kernel version to boot number
            e.g., {'6.8.0-1044-azure-fde': '0002'}
        """
        output = self.run(
            "",
            shell=True,
            sudo=True,
            force_run=True,
        ).stdout
        boot_entries: Dict[str, str] = {}

        # Sample efibootmgr output:
        # BootCurrent: 0003
        # Timeout: 0 seconds
        # BootOrder: 0002
        # Boot0000* MsTemp
        # Boot0002* Ubuntu with kernel 6.8.0-1044-azure-fde
        # Boot0003* Ubuntu with kernel 5.15.0-1102-azure
        for line in output.splitlines():
            match = self._boot_entry_pattern.match(line.strip())
            if match:
                kernel_version = match.group("kernel_version")
                boot_num = match.group("boot_num")
                boot_entries[kernel_version] = boot_num

        if not boot_entries:
            raise LisaException("No boot entries with kernel versions found.")

        return boot_entries

    def set_boot_entry(self, boot_entry: str) -> None:
        """
        Set the specified boot entry as default.
        Args:
            boot_entry: The boot entry number to set as default (e.g., '0002')
        """
        self.run(
            f"-o {boot_entry}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"failed to set boot default entry to {boot_entry}"
            ),
        )

    def set_boot_entry_to_new_kernel(
        self, boot_entries_before_kernel_update: Dict[str, str]
    ) -> None:
        """
        Update the boot entry to the new kernel version installed.
        Args:
            boot_entries_before_kernel_update:
                A dictionary of kernel versions to boot numbers before the kernel update
        """
        boot_entries_now = self.get_boot_entries_by_kernel()

        # Find new kernel entries by comparing before and after
        new_kernel_entries = {
            kernel: boot_num
            for kernel, boot_num in boot_entries_now.items()
            if kernel not in boot_entries_before_kernel_update
        }

        if not new_kernel_entries:
            available_kernels = ", ".join(boot_entries_now.keys())
            raise LisaException(
                "No new kernel boot entries found after kernel update. "
                f"Available kernels: {available_kernels}"
            )

        # Raise exception if multiple new kernels found
        if len(new_kernel_entries) > 1:
            raise LisaException(
                f"Multiple new kernel boot entries found after kernel update: "
                f"{', '.join(new_kernel_entries.keys())}. Expected only one."
            )

        latest_kernel = next(iter(new_kernel_entries))
        latest_boot_entry = new_kernel_entries[latest_kernel]
        self.set_boot_entry(latest_boot_entry)
