# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Linux


class Vgremove(Tool):
    @property
    def command(self) -> str:
        return "vgremove"

    @property
    def can_install(self) -> bool:
        return isinstance(self.node.os, Linux)

    def remove_vg(
        self, vg_name: str, force: bool = True, ignore_errors: bool = False
    ) -> None:
        """
        Remove a volume group.

        Args:
            vg_name: Name of the volume group to remove
            force: If True, skip confirmation prompts (default: True)
            ignore_errors: If True, don't raise exception on errors (default: False)
        """
        cmd_parts = ["vgremove"]
        if force:
            cmd_parts.append("-f")
        cmd_parts.append(vg_name)

        if ignore_errors:
            self.node.execute(" ".join(cmd_parts), sudo=True, no_error_log=True)
        else:
            self.node.execute(" ".join(cmd_parts), sudo=True, expected_exit_code=0)

    def _install(self) -> bool:
        linux = cast(Linux, self.node.os)
        linux.install_packages("lvm2")
        return self._check_exists()
