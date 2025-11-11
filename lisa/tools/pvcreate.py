from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Linux


class Pvcreate(Tool):
    @property
    def command(self) -> str:
        return "pvcreate"

    @property
    def can_install(self) -> bool:
        return isinstance(self.node.os, Linux)

    def create_pv(self, *devices: str) -> None:
        self.node.execute(
            f"pvcreate {' '.join(devices)}", sudo=True, expected_exit_code=0
        )

    def _install(self) -> bool:
        linux = cast(Linux, self.node.os)
        linux.install_packages("lvm2")
        return self._check_exists()
