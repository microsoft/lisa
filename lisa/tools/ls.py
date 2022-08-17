# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List, Optional, Type

from lisa.executable import Tool
from lisa.tools.powershell import PowerShell


class Ls(Tool):
    @property
    def command(self) -> str:
        return "ls"

    @property
    def can_install(self) -> bool:
        return False

    def path_exists(self, path: str, sudo: bool = False) -> bool:
        cmd_result = self.run(
            path,
            force_run=True,
            sudo=sudo,
        )
        return 0 == cmd_result.exit_code

    def list(self, path: str, sudo: bool = False) -> List[str]:
        cmd_result = self.run(
            f"-d {path}/*",
            force_run=True,
            sudo=sudo,
            shell=True,
        )

        # can fail due to insufficient permissions, non existent
        # files/dirs etc.
        if cmd_result.exit_code == 0:
            return cmd_result.stdout.split()
        else:
            return []

    def list_dir(self, path: str, sudo: bool = False) -> List[str]:
        cmd_result = self.node.execute(
            f"{self.command} -d {path}/*/",
            sudo=sudo,
            shell=True,
        )
        if cmd_result.exit_code == 0:
            return cmd_result.stdout.split()
        else:
            return []

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsLs


class WindowsLs(Ls):
    @property
    def command(self) -> str:
        return ""

    def _check_exists(self) -> bool:
        return True

    def path_exists(self, path: str, sudo: bool = False) -> bool:
        output = self.node.tools[PowerShell].run_cmdlet(
            f"Test-Path {path}",
            force_run=True,
            sudo=sudo,
        )
        return output.strip() == "True"

    def list_dir(self, path: str, sudo: bool = False) -> List[str]:
        raise NotImplementedError()
