# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Optional, Type

from lisa.executable import Tool
from lisa.tools.ls import Ls
from lisa.tools.powershell import PowerShell


class Mkdir(Tool):
    @property
    def command(self) -> str:
        return "mkdir"

    @property
    def can_install(self) -> bool:
        return False

    def create_directory(self, path: str, sudo: bool = False) -> None:
        self.run(f"-p {path}", sudo=sudo, force_run=True)

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsMkdir


class WindowsMkdir(Mkdir):
    @property
    def command(self) -> str:
        return ""

    def _check_exists(self) -> bool:
        return True

    def create_directory(self, path: str, sudo: bool = False) -> None:
        ls = self.node.tools[Ls]
        if ls.path_exists(path, sudo=sudo):
            self._log.debug(f"Folder {path} already exists")
            return

        self.node.tools[PowerShell].run_cmdlet(
            f"New-Item -ItemType Directory '{path}'", sudo=sudo
        )
