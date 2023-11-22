# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import List, Optional, Type

from lisa.executable import Tool
from lisa.util import LisaException

from .ls import Ls


class Find(Tool):
    @property
    def command(self) -> str:
        return "find"

    @property
    def can_install(self) -> bool:
        return False

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsFind

    def find_files(
        self,
        start_path: PurePath,
        name_pattern: str = "",
        path_pattern: str = "",
        file_type: str = "",
        ignore_case: bool = False,
        sudo: bool = False,
        ignore_not_exist: bool = False,
        force_run: bool = True,
    ) -> List[str]:
        if not self.node.tools[Ls].path_exists(str(start_path), sudo=sudo):
            if ignore_not_exist:
                return []
            else:
                raise LisaException(f"Path {start_path} does not exist.")

        cmd = str(start_path)
        if name_pattern:
            if ignore_case:
                cmd += f" -iname '{name_pattern}'"
            else:
                cmd += f" -name '{name_pattern}'"
        if path_pattern:
            if ignore_case:
                cmd += f" -ipath '{path_pattern}'"
            else:
                cmd += f" -path '{path_pattern}'"
        if file_type:
            cmd += f" -type '{file_type}'"

        # for possibility of newline character in the file/folder name.
        cmd += " -print0"

        result = self.run(cmd, sudo=sudo, force_run=force_run)
        if ignore_not_exist and "No such file or directory" in result.stdout:
            return []
        else:
            result.assert_exit_code()
        return list(filter(None, result.stdout.split("\x00")))


class WindowsFind(Find):
    @property
    def command(self) -> str:
        return "where"

    def find_files(
        self,
        start_path: PurePath,
        name_pattern: str = "",
        path_pattern: str = "",
        file_type: str = "",
        ignore_case: bool = False,
        sudo: bool = False,
        ignore_not_exist: bool = False,
        force_run: bool = True,
    ) -> List[str]:
        cmd = ""
        if start_path:
            cmd += f" /R {start_path}"

        cmd += f" {name_pattern}"

        results = self.run(
            cmd,
            force_run=force_run,
            expected_exit_code=0,
            expected_exit_code_failure_message="Error on find files",
        )

        return list(filter(None, results.stdout.split("\n")))
