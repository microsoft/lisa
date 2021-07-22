# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import cast

from retry import retry

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import LisaException

from .echo import Echo
from .service import Service


class Chrony(Tool):
    __leap_status_pattern = re.compile(
        r"([\w\W]*?)Leap status.*:.*Normal$", re.MULTILINE
    )
    __no_server_set = "Number of sources = 0"

    @property
    def command(self) -> str:
        return "chronyc"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        package_name = "chrony"
        posix_os.install_packages(package_name)
        return self._check_exists()

    def restart(self) -> None:
        service = self.node.tools[Service]
        # Ubuntu, Debian
        cmd_result = service.restart_service("chrony")
        if 0 != cmd_result.exit_code:
            # SLES, RHEL, CentOS
            cmd_result = service.restart_service("chronyd")
        cmd_result.assert_exit_code()

    @retry(exceptions=LisaException, tries=120, delay=0.5)
    def check_tracking(self) -> None:
        cmd_result = self.run("tracking", force_run=True)
        cmd_result.assert_exit_code()
        if not self.__leap_status_pattern.match(cmd_result.stdout):
            raise LisaException(
                f"Leap status of {self.command} tracking is not expected,"
                " please check the service status of chrony."
            )

    def check_server_setting(self) -> None:
        cmd_result = self.run("sources", shell=True, sudo=True, force_run=True)
        if self.__no_server_set in cmd_result.stdout:
            echo = self.node.tools[Echo]
            echo.run("server 0.pool.ntp.org >> /etc/chrony.conf", shell=True, sudo=True)
            echo.run("server 1.pool.ntp.org >> /etc/chrony.conf", shell=True, sudo=True)
            echo.run("server 2.pool.ntp.org >> /etc/chrony.conf", shell=True, sudo=True)
            echo.run("server 3.pool.ntp.org >> /etc/chrony.conf", shell=True, sudo=True)

    def check_sources_and_stats(self) -> None:
        cmd_result = self.run("sources")
        cmd_result.assert_exit_code()
        cmd_result = self.run("sourcestats")
        cmd_result.assert_exit_code()
