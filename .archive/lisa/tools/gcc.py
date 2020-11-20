from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Linux


class Gcc(Tool):
    @property
    def command(self) -> str:
        return "gcc"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        linux_os: Linux = cast(Linux, self.node.os)
        linux_os.install_packages("gcc")
        return self._check_exists()
