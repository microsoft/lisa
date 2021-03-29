# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from datetime import datetime

from dateutil.parser import parser

from lisa.executable import Tool
from lisa.util import LisaException


class Uptime(Tool):
    @property
    def command(self) -> str:
        return "uptime"

    def _check_exists(self) -> bool:
        return True

    def since_time(self, no_error_log: bool = True) -> datetime:
        # always force run, because it's used to detect if the system is rebooted.
        command_result = self.run("-s", force_run=True, no_error_log=no_error_log)
        if command_result.exit_code != 0:
            raise LisaException(
                f"get unexpected non-zero exit code {command_result.exit_code} "
                f"when run {self.command} -s."
            )
        return parser().parse(command_result.stdout)
