# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List, Optional

from lisa.executable import Tool
from lisa.util.process import ExecutableResult


class Grep(Tool):
    @property
    def command(self) -> str:
        return "grep"

    def _check_exists(self) -> bool:
        return True

    def _run_grep(
        self,
        pattern: str,
        file: str,
        additional_args: Optional[List[str]] = None,
        sudo: bool = False,
        force_run: bool = True,
        ignore_case: bool = False,
        invert_match: bool = False,
        max_count: Optional[int] = None,
        no_debug_log: bool = True,
    ) -> ExecutableResult:
        """
        Args:
            pattern: The pattern to search for
            file: The file path to search in
            additional_args: Additional grep arguments (e.g., ['-c'] for count)
            sudo: Whether to run with sudo
            force_run: Whether to force run
            ignore_case: Whether to ignore case (-i flag)
            invert_match: Select non-matching lines (-v flag)
            max_count: Stop after NUM matching lines (-m flag)
            no_debug_log: Whether to suppress debug logging

        Returns:
            The ExecutableResult from running grep
        """
        args = additional_args.copy() if additional_args else []

        if ignore_case:
            args.append("-i")
        if invert_match:
            args.append("-v")
        if max_count is not None:
            args.append(f"-m {max_count}")

        args_str = " ".join(args)
        cmd = f'{args_str} "{pattern}" {file}'.strip()

        result = self.run(
            cmd,
            sudo=sudo,
            force_run=force_run,
            no_debug_log=no_debug_log,
            shell=True,
        )

        # grep returns exit code 1 when no matches found, which is ok
        result.assert_exit_code(
            expected_exit_code=[0, 1],
            message="grep command failed",
        )

        return result

    def search(
        self,
        pattern: str,
        file: str,
        sudo: bool = False,
        force_run: bool = True,
        ignore_case: bool = False,
        invert_match: bool = False,
        max_count: Optional[int] = None,
        no_debug_log: bool = True,
    ) -> str:
        """
        Search for a pattern in a file using grep.
        Returns matching lines from the file.

        Args:
            pattern: The pattern to search for
            file: The file path to search in
            sudo: Whether to run with sudo
            force_run: Whether to force run
            ignore_case: Whether to ignore case (-i flag)
            invert_match: Select non-matching lines (-v flag)
            max_count: Stop after NUM matching lines (-m flag)
            no_debug_log: Whether to suppress debug logging

        Returns:
            The matching lines (one per line)
        """
        result = self._run_grep(
            pattern=pattern,
            file=file,
            sudo=sudo,
            force_run=force_run,
            ignore_case=ignore_case,
            invert_match=invert_match,
            max_count=max_count,
            no_debug_log=no_debug_log,
        )
        return result.stdout

    def count(
        self,
        pattern: str,
        file: str,
        sudo: bool = False,
        force_run: bool = True,
        ignore_case: bool = False,
        invert_match: bool = False,
        no_debug_log: bool = True,
    ) -> int:
        """
        Count the number of lines matching a pattern in a file using grep -c.

        Args:
            pattern: The pattern to search for
            file: The file path to search in
            sudo: Whether to run with sudo
            force_run: Whether to force run
            ignore_case: Whether to ignore case (-i flag)
            invert_match: Select non-matching lines (-v flag)
            no_debug_log: Whether to suppress debug logging

        Returns:
            The count of matching lines as an integer
        """
        result = self._run_grep(
            pattern=pattern,
            file=file,
            additional_args=["-c"],
            sudo=sudo,
            force_run=force_run,
            ignore_case=ignore_case,
            invert_match=invert_match,
            no_debug_log=no_debug_log,
        )
        return int(result.stdout.strip())
