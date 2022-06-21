# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from datetime import datetime

from dateutil.parser import parser

from lisa.executable import Tool
from lisa.util import LisaException


class Date(Tool):
    @property
    def command(self) -> str:
        return "date"

    def _check_exists(self) -> bool:
        return True

    def current(self, no_error_log: bool = True) -> datetime:
        # always force run to get current date time.
        command_result = self.run(
            no_error_log=no_error_log,
            force_run=True,
            timeout=10,
            expected_exit_code=0
        )
        return parser().parse(command_result.stdout)
