# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import Dict

from lisa.executable import Tool
from lisa.operating_system import Posix


class EfiBootMgr(Tool):
    # Regular expression to parse boot entries with kernel versions
    # Matches entries like: Boot0002* Ubuntu with kernel 6.8.0-1044-azure-fde
    _boot_entry_pattern = re.compile(
        r"Boot(?P<boot_num>\d+)\*?\s+(?P<boot_name>.*?)\s+with\s+kernel\s+(?P<kernel_version>[\d\.\-\w]+)"
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

    # Sample efibootmgr output:
    # BootCurrent: 0003
    # Timeout: 0 seconds
    # BootOrder: 0002
    # Boot0000* MsTemp
    # Boot0002* Ubuntu with kernel 6.8.0-1044-azure-fde
    # Boot0003* Ubuntu with kernel 5.15.0-1102-azure
    def _get_cmd_output(self, cmd: str) -> str:
        cmd_result = self.run(
            cmd,
            expected_exit_code=0,
            expected_exit_code_failure_message="failed to get ESP path",
            shell=True,
            sudo=True,
            force_run=True,
        )
        return cmd_result.stdout

    def get_boot_entries_by_kernel(self) -> Dict[str, str]:
        """
        Parse efibootmgr output and return boot entries with kernel versions as keys.

        Returns:
            Dict mapping kernel version to boot number (e.g., {'6.8.0-1044-azure-fde': 'Boot0002'})
        """
        output = self.node.execute(
            "efibootmgr",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "efibootmgr command failed to get boot entries"
            ),
        ).stdout
        boot_entries: Dict[str, str] = {}

        for line in output.splitlines():
            match = self._boot_entry_pattern.match(line.strip())
            if match:
                kernel_version = match.group("kernel_version")
                boot_num = match.group('boot_num')
                boot_entries[kernel_version] = boot_num

        return boot_entries

    def set_boot_entry(self, boot_entry: str) -> None:
        """
        Set the specified boot entry as default.
        """
        output = self.node.execute(
            f"efibootmgr -o {boot_entry}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"failed to set boot default entry to {boot_entry}"
            ),
        ).stdout
        output = self._get_cmd_output("efibootmgr")
        self.node.log.debug(f"Set boot entry output: {output}")
