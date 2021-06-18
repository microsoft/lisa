# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools import Git, Make


class Nvmecli(Tool):
    repo = "https://github.com/linux-nvme/nvme-cli"

    @property
    def command(self) -> str:
        return "nvme"

    @property
    def can_install(self) -> bool:
        return True

    def _install_from_src(self) -> None:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages([Git, Make, "pkg-config"])
        tool_path = self.get_tool_path()
        self.node.shell.mkdir(tool_path, exist_ok=True)
        git = self.node.tools[Git]
        git.clone(self.repo, tool_path)
        make = self.node.tools[Make]
        code_path = tool_path.joinpath("nvme-cli")
        make.make_and_install(cwd=code_path)

    def install(self) -> bool:
        if not self._check_exists():
            posix_os: Posix = cast(Posix, self.node.os)
            package_name = "nvme-cli"
            posix_os.install_packages(package_name)
            if not self._check_exists():
                self._install_from_src()
        return self._check_exists()
