# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import Any, List, Type

from lisa.base_tools.wget import Wget
from lisa.executable import Tool
from lisa.operating_system import Redhat
from lisa.tools import Modinfo
from lisa.util import LisaException, find_patterns_in_lines


class Waagent(Tool):
    __version_pattern = re.compile(r"(?<=\-)([^\s]+)")

    @property
    def command(self) -> str:
        return self._command

    def _check_exists(self) -> bool:
        return True

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command = "waagent"

    def get_version(self) -> str:
        result = self.run("-version")
        if result.exit_code != 0:
            self._command = "/usr/sbin/waagent"
            result = self.run("-version")
        # When the default command python points to python2,
        # we need specify python3 clearly.
        # e.g. bt-americas-inc diamondip-sapphire-v5 v5-9 9.0.53.
        if result.exit_code != 0:
            self._command = "python3 /usr/sbin/waagent"
            result = self.run("-version")
        found_version = find_patterns_in_lines(result.stdout, [self.__version_pattern])
        return found_version[0][0] if found_version[0] else ""

    def deprovision(self) -> None:
        # the deprovision doesn't delete user, because the VM may be needed. If
        # the vm need to be exported clearly, it needs to remove the current
        # user with below command:
        # self.run("-deprovision+user --force", sudo=True)
        result = self.run("-deprovision --force", sudo=True)
        result.assert_exit_code()


class VmGeneration(Tool):
    """
    This is a virtual tool to detect VM generation of Hyper-V technology.
    """

    @property
    def command(self) -> str:
        return "ls -lt /sys/firmware/efi"

    def _check_exists(self) -> bool:
        return True

    def get_generation(self) -> str:
        cmd_result = self.run()
        return "2" if cmd_result.exit_code == 0 else "1"


class LisDriver(Tool):
    """
    This is a virtual tool to detect/install LIS (Linux Integration Services) drivers.
    More info  - https://www.microsoft.com/en-us/download/details.aspx?id=55106
    """

    __version_pattern = re.compile(r"^version:[ \t]*([^ \n]*)")

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Wget, Modinfo]

    @property
    def can_install(self) -> bool:
        return (
            isinstance(self.node.os, Redhat)
            and self.node.os.release_version < "7.8.0"
        )

    def _check_exists(self) -> bool:
        return bool(isinstance(self.node.os, Redhat) and self.node.os.package_exists(
                "kmod-microsoft-hyper-v"
            ) and self.node.os.package_exists("microsoft-hyper-v"))

    def _install(self) -> bool:
        wget_tool = self.node.tools[Wget]
        lis_path = wget_tool.get("https://aka.ms/lis", str(self.node.working_path))

        result = self.node.execute(f"tar -xvzf {lis_path}")
        if result.exit_code != 0:
            raise LisaException(
                "Failed to extract tar file after downloading LIS package. "
                f"exit_code: {result.exit_code} stderr: {result.stderr}"
            )
        lis_folder_path = self.node.working_path.joinpath("LISISO")
        result = self.node.execute("./install.sh", cwd=lis_folder_path)
        if result.exit_code != 0:
            raise LisaException(
                f"Unable to install the LIS RPMs! exit_code: {result.exit_code}"
                f"stderr: {result.stderr}"
            )
        return True

    def get_version(self) -> str:
        cmd_result = self.run()
        if cmd_result.exit_code == 0:
            found_version = find_patterns_in_lines(
                cmd_result.stdout, [self.__version_pattern]
            )
        return found_version[0][0] if (found_version and found_version[0]) else ""
