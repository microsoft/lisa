import pathlib

from lisa.executable import Tool
from lisa.operating_system import Linux
from lisa.util import LisaException


class Git(Tool):
    @property
    def command(self) -> str:
        return "git"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        if isinstance(self.node.os, Linux):
            self.node.os.install_packages([self])
        else:
            raise LisaException(
                "Doesn't support to install git in Windows. "
                "Make sure git is installed and in PATH"
            )
        return self._check_exists()

    def clone(self, url: str, cwd: pathlib.PurePath) -> None:
        # git print to stderr for normal info, so set no_error_log to True.
        self.run(f"clone {url}", cwd=cwd, no_error_log=True)
