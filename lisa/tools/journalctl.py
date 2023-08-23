# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool


class Journalctl(Tool):
    @property
    def command(self) -> str:
        return "journalctl"

    def _check_exists(self) -> bool:
        return True

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
        self, boot_id: str = "", no_of_lines: int = 1000, sudo: bool = True
    ) -> str:
        result = self.run(
            f"-b {boot_id} | head -n {no_of_lines} ",
            force_run=True,
            shell=True,
            sudo=sudo,
            expected_exit_code=0,
        )
        return result.stdout
