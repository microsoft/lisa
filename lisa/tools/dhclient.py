# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import Any, Optional, Type

from lisa.base_tools import Cat
from lisa.executable import Tool
from lisa.operating_system import Debian, Fedora, Redhat, Suse
from lisa.util import LisaException, UnsupportedDistroException, find_group_in_lines

from .ls import Ls


class Dhclient(Tool):
    # timeout 300;
    _debian_pattern = re.compile(r"^(?P<default>#?)timeout (?P<number>\d+);$")
    # ipv4.dhcp-timeout=300
    _fedora_pattern = re.compile(r"^ipv4\.dhcp-timeout=+(?P<number>\d+)$")

    @property
    def command(self) -> str:
        return self._command

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command = "dhclient"

    def _check_exists(self) -> bool:
        original_command = self._command
        commands_to_check = ["dhclient", "dhcpcd"]
        for command in commands_to_check:
            self._command = command
            if super()._check_exists():
                return True
        self._command = original_command
        return False

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return DhclientFreeBSD

    @property
    def can_install(self) -> bool:
        return False

    def get_timeout(self) -> int:
        is_default_value: bool = True
        if (
            isinstance(self.node.os, Debian)
            or isinstance(self.node.os, Suse)
            or isinstance(self.node.os, Redhat)
        ):
            paths_to_check = [
                f"/etc/dhcp/{self._command}.conf",
                f"/etc/{self._command}.conf",
            ]

            ls = self.node.tools[Ls]
            config_path = next(
                (path for path in paths_to_check if ls.path_exists(path, sudo=True)), ""
            )

            if not config_path:
                raise LisaException(f"Configuration file for {self._command} not found")

            # the default value in debian is 300
            value: int = 300
            cat = self.node.tools[Cat]
            output = cat.read(config_path, sudo=True)
            group = find_group_in_lines(output, self._debian_pattern)
            if group and not group["default"]:
                value = int(group["number"])
                is_default_value = False
        elif isinstance(self.node.os, Fedora):
            # the default value in fedora is 45
            value = 45
            result = self.node.execute("NetworkManager --print-config", sudo=True)
            group = find_group_in_lines(result.stdout, self._fedora_pattern)
            if group and value != int(group["number"]):
                value = int(group["number"])
                is_default_value = False
        else:
            raise UnsupportedDistroException(os=self.node.os)

        self._log.debug(f"timeout value: {value}, is default: {is_default_value}")

        return value

    def renew(self, interface: str = "") -> None:
        if interface:
            result = self.run(
                f"-r {interface} && dhclient {interface}",
                shell=True,
                sudo=True,
                force_run=True,
            )
        else:
            result = self.run(
                "-r && dhclient",
                shell=True,
                sudo=True,
                force_run=True,
            )
        result.assert_exit_code(
            0, f"dhclient renew return non-zero exit code: {result.stdout}"
        )


class DhclientFreeBSD(Dhclient):
    @property
    def command(self) -> str:
        return "dhclient"

    def renew(self, interface: str = "") -> None:
        interface = interface or ""
        self.run(
            interface,
            shell=True,
            sudo=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="unable to renew ip address",
        )
