from typing import Optional, cast

from lisa.executable import Tool
from lisa.operating_system import Linux


class Lvcreate(Tool):
    @property
    def command(self) -> str:
        return "lvcreate"

    @property
    def can_install(self) -> bool:
        return isinstance(self.node.os, Linux)

    def create_lv(
        self,
        size: Optional[str] = None,
        name: Optional[str] = None,
        vg_name: Optional[str] = None,
        device: Optional[str] = None,
        extra: str = "",
    ) -> None:
        cmd_parts = ["lvcreate"]
        if size:
            cmd_parts.append(f"-L {size}")
        if name:
            cmd_parts.append(f"-n {name}")
        if vg_name:
            cmd_parts.append(vg_name)
        if device:
            cmd_parts.append(device)
        if extra:
            cmd_parts.append(extra)

        self.node.execute(" ".join(cmd_parts), sudo=True, expected_exit_code=0)

    def _install(self) -> bool:
        linux = cast(Linux, self.node.os)
        linux.install_packages("lvm2")
        return self._check_exists()
