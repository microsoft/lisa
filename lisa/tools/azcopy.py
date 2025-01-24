# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import PurePath
from typing import Optional, Type, Any

from lisa.executable import Tool
from lisa.tools.powershell import PowerShell


class AzCopy(Tool):
    @property
    def command(self) -> str:
        return "azcopy"

    @property
    def can_install(self) -> bool:
        return True

    def download_file(
        self,
        sas: str,
        localfile: PurePath,
        sudo: bool = False,
        timeout: int = 600,
    ) -> None:
        raise NotImplementedError()

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsAzCopy


class WindowsAzCopy(AzCopy):
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command: str = ""

    @property
    def command(self) -> str:
        return self._command

    def download_file(
        self,
        sas: str,
        localfile: PurePath,
        sudo: bool = False,
        timeout: int = 600,
    ) -> None:
        cmd = f'{self.command} {sas} "{self.node.get_str_path(localfile)}"'
        self.node.tools[PowerShell].run_cmdlet(
            cmd, sudo=sudo, timeout=timeout, fail_on_error=True
        )

    def _check_exists(self) -> bool:
        return True

    def _install(self) -> bool:
        download_path = "C:\\azcopy.zip"
        # download azcopy
        self.node.tools[PowerShell].run_cmdlet(
            f'Invoke-WebRequest -Uri "https://aka.ms/downloadazcopy-v10-windows" '
            f'-OutFile "{download_path}"',
            sudo=True,
            fail_on_error=True,
        )
        # extract azcopy
        self.node.tools[PowerShell].run_cmdlet(
            cmdlet=(
                f'Expand-Archive -Path "{download_path}" '
                f'-DestinationPath r"C:\\AZCopy\\"'
            ),
            sudo=True,
            fail_on_error=True,
        )
        # get the path of azcopy.exe
        self._command = self.node.tools[PowerShell].run_cmdlet(
            cmdlet=(
                'Get-ChildItem -Path r"C:\\AZCopy\\" -Recurse | '
                'Where-Object {{ $_.Name -eq "azcopy.exe" }} | '
                "Select-Object -ExpandProperty FullName"
            ),
            sudo=True,
            fail_on_error=True,
        )

        return True
