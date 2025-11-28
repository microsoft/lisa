# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Optional, cast

from lisa.executable import Tool
from lisa.operating_system import Linux


class Vgs(Tool):
    @property
    def command(self) -> str:
        return "vgs"

    @property
    def can_install(self) -> bool:
        return isinstance(self.node.os, Linux)

    def get_vg_info(
        self,
        vg_name: Optional[str] = None,
        options: str = "",
    ) -> str:
        """
        Get volume group information.

        Args:
            vg_name: Optional name of a specific volume group
            options: Additional options to pass to vgs
                (e.g., "-o+devices", "--noheadings")

        Returns:
            The output from the vgs command
        """
        cmd_parts = ["vgs"]
        if options:
            cmd_parts.append(options)
        if vg_name:
            cmd_parts.append(vg_name)

        result = self.node.execute(" ".join(cmd_parts), sudo=True, expected_exit_code=0)
        return result.stdout

    def list_all_vgs(self) -> str:
        """
        List all volume groups.

        Returns:
            The output from the vgs command
        """
        result = self.node.execute("vgs", sudo=True, expected_exit_code=0)
        return result.stdout

    def vg_exists(self, vg_name: str) -> bool:
        """
        Check if a volume group exists.

        Args:
            vg_name: Name of the volume group to check

        Returns:
            True if the volume group exists, False otherwise
        """
        result = self.node.execute(f"vgs {vg_name}", sudo=True, no_error_log=True)
        return result.exit_code == 0

    def _install(self) -> bool:
        linux = cast(Linux, self.node.os)
        linux.install_packages("lvm2")
        return self._check_exists()
