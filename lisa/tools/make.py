from pathlib import PurePath
from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Linux
from lisa.tools import Gcc


class Make(Tool):
    repo = "https://github.com/microsoft/ntttcp-for-linux"

    @property
    def command(self) -> str:
        return "make"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        linux_os: Linux = cast(Linux, self.node.os)
        linux_os.install_packages([self, Gcc])
        return self._check_exists()

    def make_and_install(self, cwd: PurePath) -> None:
        self.run("&& sudo make install", shell=True, cwd=cwd)
