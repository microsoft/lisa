# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import Any, Dict, List, Type

from lisa.base_tools import Cat, Wget
from lisa.executable import Tool
from lisa.operating_system import CoreOs, Redhat
from lisa.tools import Modinfo
from lisa.util import LisaException, find_patterns_in_lines, get_matched_str


class Waagent(Tool):
    __version_pattern = re.compile(r"(?<=\-)([^\s]+)")

    # ResourceDisk.MountPoint=/mnt
    # ResourceDisk.EnableSwap=n
    # ResourceDisk.EnableSwap=y
    _key_value_regex = re.compile(r"^\s*(?P<key>\S+)=(?P<value>\S+)\s*$")

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

    def get_configuration(self) -> Dict[str, str]:
        if isinstance(self.node.os, CoreOs):
            waagent_conf_file = "/usr/share/oem/waagent.conf"
        else:
            waagent_conf_file = "/etc/waagent.conf"

        config = {}
        cfg = self.node.tools[Cat].run(waagent_conf_file).stdout
        for line in cfg.splitlines():
            matched = self._key_value_regex.fullmatch(line)
            if matched:
                config[matched.group("key")] = matched.group("value")

        return config

    def get_root_device_timeout(self) -> int:
        waagent_configuration = self.get_configuration()
        return int(waagent_configuration["OS.RootDeviceScsiTimeout"])

    def get_resource_disk_mount_point(self) -> str:
        waagent_configuration = self.get_configuration()
        return waagent_configuration["ResourceDisk.MountPoint"]

    def is_swap_enabled(self) -> bool:
        waagent_configuration = self.get_configuration()
        is_swap_enabled = waagent_configuration["ResourceDisk.EnableSwap"]
        if is_swap_enabled == "y":
            return True
        elif is_swap_enabled == "n":
            return False
        else:
            raise LisaException(
                f"Unknown value for ResourceDisk.EnableSwap : {is_swap_enabled}"
            )


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
        if cmd_result.exit_code == 0:
            generation = "2"
        else:
            generation = "1"
        return generation


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
    def command(self) -> str:
        return "modinfo hv_vmbus"

    @property
    def can_install(self) -> bool:
        if (
            isinstance(self.node.os, Redhat)
            and self.node.os.information.version < "7.8.0"
        ):
            return True

        return False

    def _check_exists(self) -> bool:
        if isinstance(self.node.os, Redhat):
            # currently LIS is only supported with Redhat
            # and its derived distros
            if self.node.os.package_exists(
                "kmod-microsoft-hyper-v"
            ) and self.node.os.package_exists("microsoft-hyper-v"):
                return True
        return False

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

    def get_version(self, force: bool = False) -> str:
        cmd_result = self.run(
            force_run=force,
            expected_exit_code=0,
            expected_exit_code_failure_message="hv_vmbus module not found/loaded.",
        )

        found_version = get_matched_str(cmd_result.stdout, self.__version_pattern)
        return found_version if found_version else ""
