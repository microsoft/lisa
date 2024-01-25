# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import PurePath
from typing import Optional, Type

from lisa.executable import Tool
from lisa.tools.powershell import PowerShell


class Cp(Tool):
    @property
    def command(self) -> str:
        return "cp"

    @property
    def can_install(self) -> bool:
        return False

    def copy(
        self,
        src: PurePath,
        dest: PurePath,
        sudo: bool = False,
        cwd: Optional[PurePath] = None,
        recur: bool = False,
        timeout: int = 600,
    ) -> None:
        cmd = f"{self.node.get_str_path(src)} {self.node.get_str_path(dest)}"
        if recur:
            cmd = f"-r {cmd}"
        result = self.run(
            cmd,
            force_run=True,
            sudo=sudo,
            cwd=cwd,
            shell=True,
            timeout=timeout,
        )

        # cp copies all the files except folders in the source
        # directory to the destination directory when we do not
        # specify -r when source is a directory. Though it throws
        # an error which we can ignore.
        if "omitting directory" in result.stdout and not recur:
            return
        result.assert_exit_code()

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsCp


class WindowsCp(Cp):
    @property
    def command(self) -> str:
        return ""

    def _check_exists(self) -> bool:
        return True

    def copy(
        self,
        src: PurePath,
        dest: PurePath,
        sudo: bool = False,
        cwd: Optional[PurePath] = None,
        recur: bool = False,
        timeout: int = 600,
    ) -> None:
        cmd = (
            f'Copy-Item -Path "{self.node.get_str_path(src)}" '
            f'-Destination "{self.node.get_str_path(dest)}"'
        )

        if recur:
            cmd = f"{cmd} -Recurse"

        if cwd is not None:
            cmd = f'Push-Location "{self.node.get_str_path(cwd)}"; {cmd}; Pop-Location;'

        self.node.tools[PowerShell].run_cmdlet(
            cmd, sudo=sudo, timeout=timeout, fail_on_error=True
        )
