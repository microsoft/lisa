# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import Optional, Type

from lisa.executable import Tool
from lisa.operating_system import Alpine, Debian
from lisa.util import UnsupportedDistroException
from lisa.util.process import Process

INTERNET_PING_ADDRESS = "8.8.8.8"


class Ping(Tool):
    # ping: SO_BINDTODEVICE: Operation not permitted
    # ping: icmp open socket: Operation not permitted
    # ping: socket: Operation not permitted
    _no_permission_pattern = re.compile(
        r"ping: .* Operation not permitted",
        re.M,
    )

    # ping: sendmsg: Operation not permitted
    # The message indicates that the ICMP echo request packet has not been sent and is
    # blocked by the Control Plane ACL. Run "iptables --list" to check.
    no_sendmsg_permission_pattern = re.compile(
        r"ping: sendmsg: Operation not permitted",
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
            package_name = "iputils-ping"
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
        args: str = f"{target} -c {count} -i {interval}"
        # For Alpine, '-O' option is unrecognized, so remove '-O'
        if not isinstance(self.node.os, Alpine):
            args += " -O"
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

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return FreeBSDPing


class FreeBSDPing(Ping):
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
        args: str = ""
        # ping with '-O' in FreeBSD has issue, so remove '-O'
        # run 'ping -c 5 -i 0.2 bing.com' without sudo, will encounter below issue
        # ping: -i interval too short: Operation not permitted
        # either run ping under sudo, there is no minimal value bar for interval value
        # or without sudo, set interval >= 1
        if interval < 1 and not sudo:
            sudo = True
        args = f"-c {count} -i {interval} {target}"
        if nic_name:
            args += f" -I {nic_name}"
        if package_size:
            args += f" -s {package_size}"

        return self.run_async(args, force_run=True, sudo=sudo)
