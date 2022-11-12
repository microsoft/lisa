# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import Optional

from lisa.executable import Tool
from lisa.operating_system import Debian
from lisa.util import UnsupportedDistroException
from lisa.util.process import Process

INTERNET_PING_ADDRESS = "8.8.8.8"


class Ping(Tool):
    # ping: SO_BINDTODEVICE: Operation not permitted
    _no_permission_pattern = re.compile(
        r"ping: SO_BINDTODEVICE: Operation not permitted",
        re.M,
    )

    @property
    def command(self) -> str:
        return "ping"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        if isinstance(self.node.os, Debian):
            package_name = "inetutils-ping"
        else:
            raise UnsupportedDistroException(self.node.os)

        self.node.os.install_packages(package_name)
        return self._check_exists()

    def ping_async(
        self,
        target: str = "",
        nic_name: str = "",
        count: int = 5,
        interval: float = 0.2,
        package_size: Optional[int] = None,
        sudo: bool = False,
    ) -> Process:
        if not target:
            target = INTERNET_PING_ADDRESS
        args: str = f"{target} -c {count} -i {interval} -O"
        if nic_name:
            args += f" -I {nic_name}"
        if package_size:
            args += f" -s {package_size}"

        return self.run_async(args, force_run=True, sudo=sudo)

    def ping(
        self,
        target: str = "",
        nic_name: str = "",
        count: int = 5,
        interval: float = 0.2,
        package_size: Optional[int] = None,
        ignore_error: bool = False,
        sudo: bool = False,
    ) -> bool:
        if not target:
            target = INTERNET_PING_ADDRESS
        result = self.ping_async(
            target=target,
            nic_name=nic_name,
            count=count,
            interval=interval,
            package_size=package_size,
            sudo=sudo,
        ).wait_result()
        # for some distro like RHEL, ping with -I nic_name needs sudo
        # otherwise, ping fails with below output:
        # 'ping: SO_BINDTODEVICE: Operation not permitted'
        if not sudo and self._no_permission_pattern.findall(result.stdout):
            result = self.ping_async(
                target=target,
                nic_name=nic_name,
                count=count,
                interval=interval,
                package_size=package_size,
                sudo=True,
            ).wait_result()
        if not ignore_error:
            result.assert_exit_code(
                message=(
                    "failed on ping. The server may not be reached."
                    f" ping result is {result.stdout}"
                ),
            )
        # return ping passed or not.
        return result.exit_code == 0
