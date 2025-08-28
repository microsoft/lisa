# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePosixPath
from typing import Optional

from lisa.executable import Tool


class Journalctl(Tool):
    @property
    def command(self) -> str:
        return "journalctl"

    def _check_exists(self) -> bool:
        return True

    def logs_for_kernel(self) -> str:
        """
        Get logs for the kernel.
        """
        result = self.run(
            "--no-pager -k",
            force_run=True,
            sudo=True,
            no_debug_log=True,  # don't flood LISA logs
            expected_exit_code=0,
        )

        return result.stdout

    def logs_for_unit(self, unit_name: str, sudo: bool = True) -> str:
        result = self.run(
            f"--no-pager -u {unit_name}",
            sudo=sudo,
            force_run=True,
            no_debug_log=True,  # don't flood LISA logs
            expected_exit_code=0,
        )

        return result.stdout

    def first_n_logs_from_boot(
        self,
        boot_id: str = "",
        no_of_lines: int = 1000,
        out_file: Optional[PurePosixPath] = None,
        sudo: bool = True,
    ) -> str:
        cmd = f"-b {boot_id} --no-pager"

        if no_of_lines > 0:
            cmd = cmd + f" | head -n {no_of_lines}"

        if out_file is not None:
            cmd = cmd + f" > {out_file}"

        # if an output file is given, don't flood lisa logs
        no_debug_log = True if out_file is not None else False

        result = self.run(
            cmd,
            force_run=True,
            shell=True,
            sudo=sudo,
            no_debug_log=no_debug_log,
            expected_exit_code=0,
        )
        return result.stdout

    def filter_logs_by_pattern(
        self,
        pattern: str,
        tail_line_count: int = 1000,
        no_debug_log: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = True,
        sudo: bool = True,
    ) -> str:
        """
        Filters journalctl logs by a given pattern using grep.

        Args:
            pattern (str): Passed directly to grep. Use a valid grep pattern
                (string or regex).
            tail_line_count (int): Optionally limits the output to the last N lines.
        """
        cmd = f"--no-pager | grep '{pattern}'"

        if tail_line_count > 0:
            cmd = cmd + f" | tail -n {tail_line_count}"

        result = self.run(
            cmd,
            force_run=True,
            shell=True,
            sudo=sudo,
            no_debug_log=no_debug_log,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Failed to filter journalctl logs by pattern '{pattern}'"
            ),
        )
        return result.stdout
