# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import cast

from retry import retry

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools import Echo
from lisa.util import LisaException

from .service import Service


class Ntp(Tool):
    __leap_pattern = re.compile(r"([\w\W]*?)leap_none.*$", re.MULTILINE)
    __no_server_set = "No association ID's returned"

    @property
    def command(self) -> str:
        return "ntpq"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        package_name = "ntp"
        posix_os.install_packages(package_name)
        return self._check_exists()

    @retry(tries=300, delay=1)
    def check_leap_code(self) -> None:
        cmd_result = self.run("-c rv", shell=True, sudo=True, force_run=True)
        if not self.__leap_pattern.match(cmd_result.stdout):
            # leap_none - normal synchronized state
            # leap_alarm - NTP was never synchronized
            raise LisaException(
                "The leap code is not lean_none."
                " Please check ntp server setting and service status."
            )

    def check_server_setting(self) -> None:
        cmd_result = self.run("-np", shell=True, sudo=True, force_run=True)
        if self.__no_server_set in cmd_result.stdout:
            echo = self.node.tools[Echo]
            echo.run("server 0.pool.ntp.org >> /etc/ntp.conf", shell=True, sudo=True)
            echo.run("server 1.pool.ntp.org >> /etc/ntp.conf", shell=True, sudo=True)
            echo.run("server 2.pool.ntp.org >> /etc/ntp.conf", shell=True, sudo=True)
            echo.run("server 3.pool.ntp.org >> /etc/ntp.conf", shell=True, sudo=True)

    def restart(self) -> None:
        service = self.node.tools[Service]
        # Ubuntu, Debian, SLES 11
        cmd_result = service.restart_service("ntp")
        if 0 != cmd_result.exit_code:
            # RHEL, CentOS, SLES 12, SLES 15
            cmd_result = service.restart_service("ntpd")
        cmd_result.assert_exit_code()
