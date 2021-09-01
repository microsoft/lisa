# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import cast

from retry import retry

from lisa.executable import Tool
from lisa.operating_system import Debian, Posix, Redhat, Suse
from lisa.util import LisaException

from .echo import Echo
from .service import Service


class Chrony(Tool):
    # Leap status     : Normal
    __leap_status_pattern = re.compile(
        r"([\w\W]*?)Leap status.*:.*Normal$", re.MULTILINE
    )
    __no_server_set = "Number of sources = 0"
    __service_not_ready = "503 No such source"

    @property
    def command(self) -> str:
        return "chronyc"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("chrony")
        return self._check_exists()

    def restart(self) -> None:
        if isinstance(self.node.os, Debian):
            service_name = "chrony"
        elif isinstance(self.node.os, Redhat) or isinstance(self.node.os, Suse):
            service_name = "chronyd"
        else:
            posix_os: Posix = cast(Posix, self.node.os)
            raise LisaException(
                "Please double check chrony service name in distro "
                f"{posix_os.name} {posix_os.information.version}"
            )
        service = self.node.tools[Service]
        service.restart_service(service_name)

    @retry(exceptions=LisaException, tries=240, delay=0.5)  # type: ignore
    def check_tracking(self) -> None:
        cmd_result = self.run("tracking", force_run=True)
        cmd_result.assert_exit_code()
        if not self.__leap_status_pattern.match(cmd_result.stdout):
            raise LisaException(
                f"Leap status of {self.command} tracking is not expected,"
                " please check the service status of chrony."
            )

    def set_server_setting(self) -> None:
        cmd_result = self.run("sources", shell=True, sudo=True, force_run=True)
        if self.__no_server_set in cmd_result.stdout:
            echo = self.node.tools[Echo]
            echo.run("server 0.pool.ntp.org >> /etc/chrony.conf", shell=True, sudo=True)
            echo.run("server 1.pool.ntp.org >> /etc/chrony.conf", shell=True, sudo=True)
            echo.run("server 2.pool.ntp.org >> /etc/chrony.conf", shell=True, sudo=True)
            echo.run("server 3.pool.ntp.org >> /etc/chrony.conf", shell=True, sudo=True)

    @retry(exceptions=LisaException, tries=40, delay=0.5)  # type: ignore
    def check_sources_and_stats(self) -> None:
        cmd_result = self.run("sources", force_run=True)
        if self.__service_not_ready in cmd_result.stdout:
            raise LisaException("chrony sources is not ready, retry.")
        cmd_result.assert_exit_code()
        cmd_result = self.run("sourcestats", force_run=True)
        if self.__service_not_ready in cmd_result.stdout:
            raise LisaException("chrony sourcestats is not ready, retry.")
        cmd_result.assert_exit_code()
