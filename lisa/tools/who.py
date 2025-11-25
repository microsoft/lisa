# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from datetime import datetime

from dateutil.parser import parser

from lisa.executable import Tool
from lisa.util import get_matched_str


class Who(Tool):
    last_time_pattern = re.compile(r"^[ ]*system boot[ ]*(?P<time>.+)$")

    @property
    def command(self) -> str:
        return "who"

    @property
    def can_install(self) -> bool:
        return False

    def last_boot(self, no_error_log: bool = True) -> datetime:
        # always force run, because it's used to detect if the system is rebooted.
        print("Running 'who -b' to get last boot time")
        command_result = self.run(
            "-b",
            force_run=True,
            no_error_log=no_error_log,
            timeout=10,
        )
        print(f"'who -b' output: {command_result.stdout.strip()}")
        command_result.assert_exit_code(
            0, f"'last' return non-zero exit code: {command_result.stderr}"
        )
        print("'who -b' executed successfully")
        datetime_output = get_matched_str(command_result.stdout, self.last_time_pattern)
        print(f"Parsed datetime string: {datetime_output}")
        return parser().parse(datetime_output)  # type: ignore
