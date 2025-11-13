# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Optional, cast

from lisa.executable import Tool
from lisa.operating_system import Linux


class Lvs(Tool):
    @property
    def command(self) -> str:
        return "lvs"

    @property
    def can_install(self) -> bool:
        return isinstance(self.node.os, Linux)

    def get_lv_info(
        self,
        lv_path: Optional[str] = None,
        options: str = "",
    ) -> str:
        """
        Get logical volume information.

        Args:
            lv_path: Optional path to a specific logical volume
                (e.g., "vgname/lvname")
            options: Additional options to pass to lvs
                (e.g., "-o+devices", "--noheadings")

        Returns:
            The output from the lvs command
        """
        cmd_parts = ["lvs"]
        if options:
            cmd_parts.append(options)
        if lv_path:
            cmd_parts.append(lv_path)

        result = self.node.execute(" ".join(cmd_parts), sudo=True, expected_exit_code=0)
        return result.stdout

    def get_lv_layout(self, vg_name: str, lv_name: str) -> str:
        """
        Get the layout of a logical volume.

        Args:
            vg_name: Volume group name
            lv_name: Logical volume name

        Returns:
            The layout string (e.g., "linear", "cache", "raid1")
        """
        result = self.node.execute(
            f"lvs --noheadings -o lv_layout {vg_name}/{lv_name}",
            sudo=True,
            expected_exit_code=0,
        )
        return result.stdout.strip()

    def list_all_lvs(
        self,
        vg_name: Optional[str] = None,
        include_hidden: bool = False,
    ) -> str:
        """
        List all logical volumes.

        Args:
            vg_name: Optional volume group name to filter by
            include_hidden: If True, include hidden volumes (default: False)

        Returns:
            The output from the lvs command
        """
        cmd_parts = ["lvs"]
        if include_hidden:
            cmd_parts.append("-a")
        if vg_name:
            cmd_parts.append(vg_name)

        result = self.node.execute(" ".join(cmd_parts), sudo=True, expected_exit_code=0)
        return result.stdout

    def _install(self) -> bool:
        linux = cast(Linux, self.node.os)
        linux.install_packages("lvm2")
        return self._check_exists()
