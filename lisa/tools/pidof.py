from typing import List, cast

from lisa.executable import Tool
from lisa.operating_system import FreeBSD, Posix


class Pidof(Tool):
    @property
    def command(self) -> str:
        return "pidof"

    @property
    def can_install(self) -> bool:
        if isinstance(self.node.os, FreeBSD):
            return True
        else:
            return False

    def get_pids(self, process_name: str, sudo: bool = False) -> List[str]:
        pids = []
        # it's fine to fail
        result = self.run(process_name, force_run=True, shell=True, sudo=sudo)
        if result.exit_code == 0:
            pids = [x.strip() for x in result.stdout.split(" ")]
        return pids

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("pidof")
        return self._check_exists()
