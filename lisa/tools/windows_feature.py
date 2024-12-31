# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, List

from lisa.executable import Tool
from lisa.operating_system import Windows
from lisa.tools.powershell import PowerShell
from lisa.util import LisaException


# WindowsFeature management tool for Windows Servers.
# It can install, uninstall, and check the status of Windows features.
# Hyper-V, DHCP etc. are examples of Windows features.
# This tool uses PowerShell to manage Windows features.
# Not supported on PC versions like Windows 10, 11 etc.
class WindowsFeature(Tool):
    @property
    def command(self) -> str:
        return ""

    @property
    def can_install(self) -> bool:
        return False

    def _check_exists(self) -> bool:
        assert isinstance(self.node.os, Windows)
        try:
            self.node.tools[PowerShell].run_cmdlet(
                "Get-WindowsFeature",
                force_run=True,
            )
            self._log.debug("'Get-WindowsFeature' is installed")
            return True
        except LisaException as e:
            self._log.debug(f"'Get-WindowsFeature' is not available: {e}")
            return False

    def install_feature(self, name: str) -> None:
        if self.is_installed(name):
            self._log.debug(f"Feature {name} is already installed.")
            return
        self.node.tools[PowerShell].run_cmdlet(
            f"Install-WindowsFeature -Name {name} -IncludeManagementTools",
            force_run=True,
        )

    def uninstall_feature(self, name: str) -> None:
        if not self.is_installed(name):
            self._log.debug(f"Feature {name} is not installed.")
            return
        self.node.tools[PowerShell].run_cmdlet(
            f"Uninstall-WindowsFeature -Name {name}",
            force_run=True,
        )

    def is_installed(self, name: str) -> bool:
        return bool(
            self.node.tools[PowerShell].run_cmdlet(
                f"Get-WindowsFeature -Name {name} | Select-Object -ExpandProperty Installed",  # noqa: E501
                force_run=True,
                fail_on_error=False,
            ).strip()
            == "True"
        )
