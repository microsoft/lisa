import pathlib
from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Linux


class Git(Tool):
    @property
    def command(self) -> str:
        return "git"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        linux_os: Linux = cast(Linux, self.node.os)
        linux_os.install_packages([self])
        return self._check_exists()

    def clone(self, url: str, cwd: pathlib.PurePath) -> None:
        # git print to stderr for normal info, so set no_error_log to True.
        self.run(f"clone {url}", cwd=cwd, no_error_log=True)
