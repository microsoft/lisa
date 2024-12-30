# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any

from lisa.executable import Tool
from lisa.tools.powershell import PowerShell


class WindowsFeature(Tool):
    @property
    def command(self) -> str:
        return ""

    @property
    def can_install(self) -> bool:
        return False

    def _check_exists(self) -> bool:
        return True

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._powershell = self.node.tools[PowerShell]

    def install_feature(self, name: str) -> None:
        if self.is_installed(name):
            self._log.debug(f"Feature {name} is already installed.")
            return
        self._powershell.run_cmdlet(
            f"Install-WindowsFeature -Name {name} -IncludeManagementTools",
            force_run=True,
        )

    def uninstall_feature(self, name: str) -> None:
        if not self.is_installed(name):
            self._log.debug(f"Feature {name} is not installed.")
            return
        self._powershell.run_cmdlet(
            f"Uninstall-WindowsFeature -Name {name}",
            force_run=True,
        )

    def is_installed(self, name: str) -> bool:
        return (
            self._powershell.run_cmdlet(
                f"Get-WindowsFeature -Name {name} | Select-Object -ExpandProperty Installed",  # noqa: E501
                force_run=True,
            ).strip()
            == "True"
        )

    def get_installed_features(self) -> list[str]:
        return (
            self._powershell.run_cmdlet(
                "Get-WindowsFeature | Where-Object { $_.Installed -eq $true } | Select-Object -ExpandProperty Name",  # noqa: E501
                force_run=True,
            )
            .strip()
            .split("\n")
        )

    def get_available_features(self) -> list[str]:
        return (
            self._powershell.run_cmdlet(
                "Get-WindowsFeature | Where-Object { $_.Installed -eq $false } | Select-Object -ExpandProperty Name",  # noqa: E501
                force_run=True,
            )
            .strip()
            .split("\n")
        )
