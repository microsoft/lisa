# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Linux


class Lvremove(Tool):
    @property
    def command(self) -> str:
        return "lvremove"

    @property
    def can_install(self) -> bool:
        return isinstance(self.node.os, Linux)

    def remove_lv(
        self, lv_path: str, force: bool = True, ignore_errors: bool = False
    ) -> None:
        """
        Remove a logical volume.

        Args:
            lv_path: Full path to the logical volume (e.g., "vgname/lvname")
            force: If True, skip confirmation prompts (default: True)
            ignore_errors: If True, don't raise exception on errors (default: False)
        """
        cmd_parts = ["lvremove"]
        if force:
            cmd_parts.append("-f")
        cmd_parts.append(lv_path)

        if ignore_errors:
            self.node.execute(" ".join(cmd_parts), sudo=True, no_error_log=True)
        else:
            self.node.execute(" ".join(cmd_parts), sudo=True, expected_exit_code=0)

    def _install(self) -> bool:
        linux = cast(Linux, self.node.os)
        linux.install_packages("lvm2")
        return self._check_exists()
