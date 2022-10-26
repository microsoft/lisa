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
