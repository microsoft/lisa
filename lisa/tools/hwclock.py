# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import get_matched_str


class Hwclock(Tool):
    # matching 4-digit year between whitespace
    # or at the beginning of a line
    # example: 2022 from '2022-02-04 11:38:06.949136+0000'
    # or 2018 from 'Fri 07 Sep 2018 11:26:52 AM CEST .838868 seconds'
    # will be matched
    _YEAR_PATTERN = re.compile(r"^(?:[\w\W]*?)(\d{4})(?:[-\s])")

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

    def set_hardware_time(self, time: str) -> None:
        cmd_result = self.run(f"--set --date='{time}'", shell=True, sudo=True)
        cmd_result.assert_exit_code()

    def get_hardware_time_year(self) -> str:
        cmd_result = self.run(sudo=True)
        cmd_result.assert_exit_code()
        # Ubuntu 16.4.0 format: Fri 07 Sep 2018 11:26:52 AM CEST .838868 seconds
        # other hwclock format: '2022-02-04 11:38:06.949136+0000'
        year = get_matched_str(cmd_result.stdout, self._YEAR_PATTERN)
        return year
