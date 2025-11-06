from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Linux


class Vgcreate(Tool):
    @property
    def command(self) -> str:
        return "vgcreate"

    @property
    def can_install(self) -> bool:
        return isinstance(self.node.os, Linux)

    def create_vg(self, vg_name: str, *devices: str) -> None:
        self.node.execute(
            f"vgcreate {vg_name} {' '.join(devices)}", sudo=True, expected_exit_code=0
        )

    def _install(self) -> bool:
        linux = cast(Linux, self.node.os)
        linux.install_packages("lvm2")
        return self._check_exists()
