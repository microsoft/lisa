# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Optional

from lisa.executable import Tool


class Lvs(Tool):
    @property
    def command(self) -> str:
        return "lvs"

    @property
    def can_install(self) -> bool:
        return True

    def get_lv_info(
        self,
        lv_path: Optional[str] = None,
        options: str = "",
        sudo: bool = True,
    ) -> str:
        """
        Get logical volume information.

        Args:
            lv_path: Optional path to a specific logical volume
                (e.g., "vgname/lvname")
            options: Additional options to pass to lvs
                (e.g., "-o+devices", "--noheadings")
            sudo: Whether to run with sudo (default: True)

        Returns:
            The output from the lvs command
        """
        cmd_parts = ["lvs"]
        if options:
            cmd_parts.append(options)
        if lv_path:
            cmd_parts.append(lv_path)

        result = self.node.execute(" ".join(cmd_parts), sudo=sudo, expected_exit_code=0)
        return result.stdout

    def get_lv_layout(self, vg_name: str, lv_name: str, sudo: bool = True) -> str:
        """
        Get the layout of a logical volume.

        Args:
            vg_name: Volume group name
            lv_name: Logical volume name
            sudo: Whether to run with sudo (default: True)

        Returns:
            The layout string (e.g., "linear", "cache", "raid1")
        """
        result = self.node.execute(
            f"lvs --noheadings -o lv_layout {vg_name}/{lv_name}",
            sudo=sudo,
            expected_exit_code=0,
        )
        return result.stdout.strip()

    def list_all_lvs(
        self,
        vg_name: Optional[str] = None,
        include_hidden: bool = False,
        sudo: bool = True,
    ) -> str:
        """
        List all logical volumes.

        Args:
            vg_name: Optional volume group name to filter by
            include_hidden: If True, include hidden volumes (default: False)
            sudo: Whether to run with sudo (default: True)

        Returns:
            The output from the lvs command
        """
        cmd_parts = ["lvs"]
        if include_hidden:
            cmd_parts.append("-a")
        if vg_name:
            cmd_parts.append(vg_name)

        result = self.node.execute(" ".join(cmd_parts), sudo=sudo, expected_exit_code=0)
        return result.stdout

    def _install(self) -> bool:
        self.node.os.install_packages("lvm2")
        return self._check_exists()
