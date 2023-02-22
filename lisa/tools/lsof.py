from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix


class Lsof(Tool):
    @property
    def command(self) -> str:
        return "lsof"

    @property
    def can_install(self) -> bool:
        return True

    def is_port_opened(self, port: int) -> bool:
        cmd = f"-i :{port}"
        result = self.run(cmd, force_run=True, shell=True, sudo=True)
        return result.exit_code == 0

    def is_port_opened_per_process_name(
        self, process_name: str, protocol: str = "TCP"
    ) -> bool:
        cmd = f"-i{protocol} -P -n | grep -i {process_name}"
        result = self.run(cmd, force_run=True, shell=True, sudo=True)
        return result.exit_code == 0

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("lsof")
        return self._check_exists()
