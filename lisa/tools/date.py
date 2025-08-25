# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from datetime import datetime
from typing import Optional, Type

from dateutil.parser import parser

from lisa.executable import Tool


class Date(Tool):
    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return DateFreeBSD

    @property
    def command(self) -> str:
        return "date"

    def _check_exists(self) -> bool:
        return True

    def current(self, no_error_log: bool = True) -> datetime:
        # always force run to get current date time.
        command_result = self.run(no_error_log=no_error_log, force_run=True, timeout=10)
        command_result.assert_exit_code(
            0, f"'Date' return non-zero exit code: {command_result.stderr}"
        )
        return parser().parse(command_result.stdout)  # type: ignore

    def set(self, new_date: datetime) -> None:
        self.run(
            f"--set='{new_date.isoformat()}'",
            sudo=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to set date time.",
        )


class DateFreeBSD(Date):
    def set(self, new_date: datetime) -> None:
        self.run(
            f"'{new_date.strftime('%Y%m%d%H%M')}'",
            sudo=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to set date time.",
        )
