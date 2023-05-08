from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix


class Sleep(Tool):
    @property
    def command(self) -> str:
        return "sleep"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        package_name = "coreutils"
        posix_os.install_packages(package_name)
        return self._check_exists()

    # Pause for NUMBER seconds.  SUFFIX may be 's' for seconds (the
    # default), 'm' for minutes, 'h' for hours or 'd' for days.  NUMBER
    # need not be an integer.  Given two or more arguments, pause for
    # the amount of time specified by the sum of their values.

    def sleep_seconds(self, delay: int = 5) -> None:
        self.run(parameters=f"{delay}", shell=True, force_run=True)
