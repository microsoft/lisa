# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from datetime import datetime
from typing import cast

from dateutil.parser import parser
from retry import retry

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import LisaException


class Hwclock(Tool):
    @property
    def command(self) -> str:
        return "hwclock"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        package_name = "util-linux"
        posix_os.install_packages(package_name)
        return self._check_exists()

    def set_rtc_clock_to_system_time(self) -> None:
        cmd_result = self.run("--systohc", shell=True, sudo=True)
        cmd_result.assert_exit_code()

    def set_datetime(self, time: datetime) -> None:
        self.run(
            f"--set --date='{time}'",
            shell=True,
            sudo=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to set date",
        )

    @retry(exceptions=LisaException, tries=20, delay=0.5)
    def get(self, no_error_log: bool = True) -> datetime:
        command_result = self.run(
            no_error_log=no_error_log,
            force_run=True,
            sudo=True,
            timeout=10,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to get date",
        )
        return parser().parse(command_result.stdout)
