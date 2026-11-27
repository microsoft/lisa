# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import List, Optional, Type, Union

from lisa.executable import ExecutableResult, Tool
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

    def _build_pattern_conditions(
        self,
        pattern: Union[str, List[str]],
        option_name: str,
        ignore_case: bool = False,
    ) -> str:
        """
        Build find command conditions for name or path patterns.

        Args:
            pattern: Single pattern string or list of patterns
            option_name: The find option name ('name' or 'path')
            ignore_case: Whether to use case-insensitive matching

        Returns:
            String with find command conditions, e.g.,
            "\\( -name '*.txt' -o -name '*.log' \\)"
        """
        if not pattern:
            return ""

        # Ensure pattern is a list
        if isinstance(pattern, str):
            pattern = [pattern]

        # Build the pattern conditions with -o (OR) between patterns
        option_prefix = f"-i{option_name}" if ignore_case else f"-{option_name}"
        conditions = []
        for p in pattern:
            conditions.append(f"{option_prefix} '{p}'")

        return " \\( " + " -o ".join(conditions) + " \\)"

    def _build_match_conditions(
        self,
        name_pattern: Union[str, List[str]],
        path_pattern: Union[str, List[str]],
        file_type: str,
        ignore_case: bool,
    ) -> str:
        cmd = self._build_pattern_conditions(name_pattern, "name", ignore_case)
        cmd += self._build_pattern_conditions(path_pattern, "path", ignore_case)
        if file_type:
            cmd += f" -type '{file_type}'"
        return cmd

    def find_files(
        self,
        start_path: PurePath,
        name_pattern: Union[str, List[str]] = "",
        path_pattern: Union[str, List[str]] = "",
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
        cmd += self._build_match_conditions(
            name_pattern, path_pattern, file_type, ignore_case
        )

        # for possibility of newline character in the file/folder name.
        cmd += " -print0"

        result = self.run(cmd, sudo=sudo, shell=True, force_run=force_run)
        if ignore_not_exist and "No such file or directory" in result.stdout:
            return []
        else:
            result.assert_exit_code()
        return list(filter(None, result.stdout.split("\x00")))

    def delete_files(
        self,
        start_path: PurePath,
        name_pattern: Union[str, List[str]] = "",
        path_pattern: Union[str, List[str]] = "",
        file_type: str = "",
        ignore_case: bool = False,
        min_depth: int = 0,
        sudo: bool = False,
        expected_exit_code: Optional[int] = 0,
    ) -> ExecutableResult:
        """
        Delete the entries under start_path that match the given conditions.
        With no conditions, everything is deleted. min_depth=1 keeps start_path
        itself. Pass expected_exit_code=None to inspect the result instead of
        asserting, as find exits non-zero if any single entry cannot be deleted.
        """
        cmd = str(start_path)
        if min_depth:
            cmd += f" -mindepth {min_depth}"
        cmd += self._build_match_conditions(
            name_pattern, path_pattern, file_type, ignore_case
        )
        # -delete must come last, otherwise find deletes before filtering.
        cmd += " -delete"

        return self.run(
            cmd,
            sudo=sudo,
            shell=True,
            force_run=True,
            expected_exit_code=expected_exit_code,
        )


class WindowsFind(Find):
    @property
    def command(self) -> str:
        return "where"

    def find_files(
        self,
        start_path: PurePath,
        name_pattern: Union[str, List[str]] = "",
        path_pattern: Union[str, List[str]] = "",
        file_type: str = "",
        ignore_case: bool = False,
        sudo: bool = False,
        ignore_not_exist: bool = False,
        force_run: bool = True,
    ) -> List[str]:
        cmd = ""
        if start_path:
            cmd += f" /R {start_path}"

        # Handle name_pattern as string or list (Windows Find is simpler)
        if name_pattern:
            if isinstance(name_pattern, list):
                # For Windows, we'll just use the first pattern
                # as the where command doesn't support multiple patterns easily
                cmd += f" {name_pattern[0]}"
            else:
                cmd += f" {name_pattern}"

        results = self.run(
            cmd,
            force_run=force_run,
            expected_exit_code=0,
            expected_exit_code_failure_message="Error on find files",
        )

        return list(filter(None, results.stdout.split("\n")))

    def delete_files(
        self,
        start_path: PurePath,
        name_pattern: Union[str, List[str]] = "",
        path_pattern: Union[str, List[str]] = "",
        file_type: str = "",
        ignore_case: bool = False,
        min_depth: int = 0,
        sudo: bool = False,
        expected_exit_code: Optional[int] = 0,
    ) -> ExecutableResult:
        raise NotImplementedError
