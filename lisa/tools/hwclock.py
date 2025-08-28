# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from datetime import datetime
from typing import Optional, Type, cast

from dateutil.parser import parser
from retry import retry

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import LisaException


class Hwclock(Tool):
    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return HwclockFreebsd

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
        if not self._check_exists():
            package_name = "util-linux-extra"
            posix_os.install_packages(package_name)
        return self._check_exists()

    def set_rtc_clock_to_system_time(self) -> None:
        cmd_result = self.run("--systohc", shell=True, sudo=True)
        cmd_result.assert_exit_code()

    def set_datetime(
        self, time: datetime, time_format: str = "%Y-%m-%d %H:%M:%S"
    ) -> None:
        # The most commonly used format that is Linux-compatible is ISO 8601 format
        # which is "YYYY-MM-DD HH:MM:SS".
        set_time = time.strftime(time_format)
        self.run(
            f"--set --date='{set_time}'",
            shell=True,
            sudo=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to set date",
        )

    @retry(exceptions=LisaException, tries=20, delay=1)  # type: ignore
    def get(self, no_error_log: bool = True) -> datetime:
        command_result = self.run(
            no_error_log=no_error_log,
            force_run=True,
            sudo=True,
            timeout=60,
        )
        if command_result.exit_code != 0:
            raise LisaException(
                f"fail to run hwclock, output: {command_result.stdout},"
                f" error: {command_result.stderr}"
            )
        return parser().parse(command_result.stdout)  # type: ignore


class HwclockFreebsd(Hwclock):
    @property
    def command(self) -> str:
        return ""

    @property
    def can_install(self) -> bool:
        return False

    def _check_exists(self) -> bool:
        return True

    def set_rtc_clock_to_system_time(self) -> None:
        self.node.execute(cmd="adjkerntz -i", expected_exit_code=0)
