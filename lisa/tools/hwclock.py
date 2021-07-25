# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix


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
