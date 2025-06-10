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

    def generate_renew_command(self, interface: str = "eth0") -> str:
        if "dhclient" in self._command:
            option = "-r"
        elif "dhcpcd" in self._command:
            option = "-k"
        else:
            raise LisaException(f"Unsupported command: {self._command}")
        return f"{self._command} {option} {interface}; {self._command} {interface}"

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
                f"/usr/lib/dracut/modules.d/40network/{self._command}.conf",
                f"/usr/lib/dracut/modules.d/35network-legacy/{self._command}.conf",
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
        # Determine the appropriate option based on the command
        if "dhclient" in self._command:
            option = "-r"
        elif "dhcpcd" in self._command:
            option = "-k"
        else:
            raise ValueError(f"Unsupported command: {self._command}")

        # If an interface is provided, use it; otherwise, use the default interface
        if interface:
            self._log.debug(f"Releasing IP for interface {interface} using {option}")
            release_result = self.run(
                f" {option} {interface}",
                shell=True,
                sudo=True,
                force_run=True,
            )
            if release_result.exit_code == 0:
                self._log.debug(f"Successfully released IP for interface {interface}")
            else:
                self._log.warning(
                    f"Failed to release IP for interface {interface}: "
                    f"{release_result.stdout}"
                )
            self._log.debug(
                f"Assigning IP to interface {interface} using {self._command}"
            )
            assign_result = self.run(
                f" {interface}",
                shell=True,
                sudo=True,
                force_run=True,
            )
            assign_result.assert_exit_code(
                0,
                f"{self._command} failed to assign IP to {interface}: "
                f"{assign_result.stdout}",
            )
        else:
            # If no interface is provided, execute the command globally
            self._log.debug(f"Executing {self._command} globally with option {option}")
            release_result = self.run(
                f" {option}",
                shell=True,
                sudo=True,
                force_run=True,
            )
            if release_result.exit_code == 0:
                self._log.debug(
                    f"Successfully executed {self._command} for all interfaces"
                )
            else:
                self._log.warning(
                    f"Failed to execute {self._command} for all interfaces: "
                    f"{release_result.stdout}"
                )
            assign_result = self.run(
                "",
                shell=True,
                sudo=True,
                force_run=True,
            )
            assign_result.assert_exit_code(
                0,
                f"{self._command} failed to assign IPs to all interfaces: "
                f"{assign_result.stdout}",
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
