# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import cast

from retry import retry

from lisa.executable import Tool
from lisa.operating_system import BSD, CBLMariner, Debian, Posix, Redhat, Suse
from lisa.tools import Echo, Service
from lisa.util import LisaException


class Ntp(Tool):
    # associd=0 status=0614 leap_none, sync_ntp, 1 event, freq_mode,
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
        posix_os.install_packages("ntp")
        return self._check_exists()

    @retry(tries=300, delay=1)  # type: ignore
    def check_leap_code(self) -> None:
        cmd_result = self.run("-c rv", shell=True, sudo=True, force_run=True)
        if not self.__leap_pattern.match(cmd_result.stdout):
            # leap_none - normal synchronized state
            # leap_alarm - NTP was never synchronized
            raise LisaException(
                "The leap code is not lean_none."
                " Please check ntp server setting and service status."
            )

    def set_server_setting(self) -> None:
        cmd_result = self.run("-np", shell=True, sudo=True, force_run=True)
        if self.__no_server_set in cmd_result.stdout:
            echo = self.node.tools[Echo]
            echo.run("server 0.pool.ntp.org >> /etc/ntp.conf", shell=True, sudo=True)
            echo.run("server 1.pool.ntp.org >> /etc/ntp.conf", shell=True, sudo=True)
            echo.run("server 2.pool.ntp.org >> /etc/ntp.conf", shell=True, sudo=True)
            echo.run("server 3.pool.ntp.org >> /etc/ntp.conf", shell=True, sudo=True)

    def restart(self) -> None:
        if isinstance(self.node.os, Debian) or (
            isinstance(self.node.os, Suse)
            and self.node.os.information.version <= "11.0.0"
        ):
            service_name = "ntp"
        elif (
            isinstance(self.node.os, Redhat)
            or (
                isinstance(self.node.os, Suse)
                and self.node.os.information.version >= "12.0.0"
            )
            or isinstance(self.node.os, CBLMariner)
            or isinstance(self.node.os, BSD)
        ):
            service_name = "ntpd"
        else:
            posix_os: Posix = cast(Posix, self.node.os)
            raise LisaException(
                "Please double check ntp service name in distro "
                f"{posix_os.name} {posix_os.information.version}"
            )
        service = self.node.tools[Service]
        service.restart_service(service_name)
