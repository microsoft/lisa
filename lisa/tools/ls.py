# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
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
            f"-p -d {path}/*",
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

    def is_file(self, path: PurePath, sudo: bool = False) -> bool:
        # If `ls -al <path>` returns more than one line, it is a directory, else
        # it is a file. This is because `ls -al <path>` returns info of the dir and
        # parent dir.
        path_str = self.node.get_str_path(path)
        cmd_result = self.run(
            f"-al {path_str}",
            force_run=True,
            sudo=sudo,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"Failed to check if {path_str} "
            "is a file",
        )

        return len(cmd_result.stdout.splitlines()) == 1

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsLs


class WindowsLs(Ls):
    @property
    def command(self) -> str:
        return ""

    def _check_exists(self) -> bool:
        return True

    def is_file(self, path: PurePath, sudo: bool = False) -> bool:
        output = self.node.tools[PowerShell].run_cmdlet(
            f"Test-Path {path} -PathType Leaf",
            force_run=True,
            sudo=sudo,
        )

        return output.strip() == "True"

    def path_exists(self, path: str, sudo: bool = False) -> bool:
        output = self.node.tools[PowerShell].run_cmdlet(
            f"Test-Path {path}",
            force_run=True,
            sudo=sudo,
        )
        return output.strip() == "True"

    def list(self, path: str, sudo: bool = False) -> List[str]:
        command = f'Get-ChildItem -Path "{path}" | Select-Object -ExpandProperty Name'
        output = self.node.tools[PowerShell].run_cmdlet(
            cmdlet=command,
            force_run=True,
            sudo=sudo,
        )
        if output:
            return output.split()
        else:
            return []

    def list_dir(self, path: str, sudo: bool = False) -> List[str]:
        raise NotImplementedError()
