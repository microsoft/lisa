# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Optional

from lisa.executable import Tool


class Grep(Tool):
    @property
    def command(self) -> str:
        return "grep"

    def _check_exists(self) -> bool:
        return True

    def search(
        self,
        pattern: str,
        file: str,
        sudo: bool = False,
        force_run: bool = True,
        ignore_case: bool = False,
        count_only: bool = False,
        invert_match: bool = False,
        max_count: Optional[int] = None,
        no_debug_log: bool = True,
    ) -> str:
        """
        Search for a pattern in a file using grep.
        This is more efficient than reading the entire file when dealing
        with large files.

        Args:
            pattern: The pattern to search for
            file: The file path to search in
            sudo: Whether to run with sudo
            force_run: Whether to force run
            ignore_case: Whether to ignore case (-i flag)
            count_only: Return only count of matches (-c flag)
            invert_match: Select non-matching lines (-v flag)
            max_count: Stop after NUM matching lines (-m flag)
            no_debug_log: Whether to suppress debug logging

        Returns:
            The grep output (matching lines or count)
        """
        args = []

        if ignore_case:
            args.append("-i")
        if count_only:
            args.append("-c")
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
        if result.exit_code not in [0, 1]:
            result.assert_exit_code()

        return result.stdout
