# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Optional, Type

from lisa.executable import Tool
from lisa.tools.ls import Ls
from lisa.tools.powershell import PowerShell


class Rm(Tool):
    @property
    def command(self) -> str:
        return "rm"

    @property
    def can_install(self) -> bool:
        return False

    def remove_file(self, path: str, sudo: bool = False) -> None:
        self.run(path, sudo=sudo, force_run=True)

    def remove_directory(self, path: str, sudo: bool = False) -> None:
        self.run(f"-rf {path}", sudo=sudo, force_run=True)

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsRm


class WindowsRm(Rm):
    @property
    def command(self) -> str:
        return ""

    def _check_exists(self) -> bool:
        return True

    def remove_file(self, path: str, sudo: bool = False) -> None:
        ls = self.node.tools[Ls]
        if not ls.path_exists(path, sudo=sudo):
            self._log.debug(f"File {path} does not exist")
            return

        self.node.tools[PowerShell].run_cmdlet(f"Remove-Item {path} -Force", sudo=sudo)

    def remove_directory(self, path: str, sudo: bool = False) -> None:
        raise NotImplementedError
