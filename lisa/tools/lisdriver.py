# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import List, Type

from lisa.base_tools import Wget
from lisa.executable import Tool
from lisa.operating_system import Redhat
from lisa.tools.tar import Tar
from lisa.util import UnsupportedDistroException, UnsupportedKernelException
from lisa.util.process import ExecutableResult

from .modinfo import Modinfo


class LisDriver(Tool):
    """
    This is a virtual tool to detect/install LIS (Linux Integration Services) drivers.
    More info  - https://www.microsoft.com/en-us/download/details.aspx?id=55106
    """

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

        raise UnsupportedDistroException(
            self.node.os, "lis driver can't be installed on this distro"
        )

    def download(self) -> PurePath:
        if not self.node.shell.exists(self.node.working_path.joinpath("LISISO")):
            wget_tool = self.node.tools[Wget]
            lis_path = wget_tool.get("https://aka.ms/lis", str(self.node.working_path))

            tar = self.node.tools[Tar]
            tar.extract(file=lis_path, dest_dir=str(self.node.working_path))
        return self.node.working_path.joinpath("LISISO")

    def get_version(self, force_run: bool = False) -> str:
        # in some distro, the vmbus is builtin, the version cannot be gotten.
        modinfo = self.node.tools[Modinfo]
        return modinfo.get_version("hv_vmbus")

    def install_from_iso(self) -> ExecutableResult:
        lis_folder_path = self.download()
        return self.node.execute("./install.sh", cwd=lis_folder_path, sudo=True)

    def uninstall_from_iso(self) -> ExecutableResult:
        lis_folder_path = self.download()
        return self.node.execute("./uninstall.sh", cwd=lis_folder_path, sudo=True)

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
        result = self.install_from_iso()
        if "Unsupported kernel version" in result.stdout:
            raise UnsupportedKernelException(self.node.os)
        result.assert_exit_code(
            0,
            f"Unable to install the LIS RPMs! exit_code: {result.exit_code}"
            f"stderr: {result.stderr}",
        )
        self.node.reboot(360)
        return True
