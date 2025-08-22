# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from datetime import datetime
from typing import Optional, Type

from dateutil.parser import parser

from lisa.executable import Tool
from lisa.tools.powershell import PowerShell


class Uptime(Tool):
    @property
    def command(self) -> str:
        return "uptime"

    def _check_exists(self) -> bool:
        return True

    def since_time(self, no_error_log: bool = True, timeout: int = 600) -> datetime:
        # always force run, because it's used to detect if the system is rebooted.
        command_result = self.run(
            "-s", force_run=True, no_error_log=no_error_log, expected_exit_code=0
        )
        return parser().parse(command_result.stdout)  # type: ignore

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsUptime


class WindowsUptime(Uptime):
    # 3/8/2022 10:47:19 PM
    DATETIME_REGEX = re.compile(r".+\n.*-+.*\n(?P<cpu>.*)")

    @property
    def command(self) -> str:
        return ""

    def _check_exists(self) -> bool:
        return True

    def since_time(self, no_error_log: bool = True, timeout: int = 600) -> datetime:
        powershell = self.node.tools[PowerShell]

        # get the last boot time
        result = powershell.run_cmdlet(
            "Get-CimInstance -ClassName win32_operatingsystem | select lastbootuptime",
            force_run=True,
            timeout=timeout,
        )

        # extract date time string from the following result format:
        datetime_str = self.DATETIME_REGEX.findall(result)[0]

        return parser().parse(datetime_str)  # type: ignore
