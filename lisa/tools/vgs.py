# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Optional

from lisa.executable import Tool


class Vgs(Tool):
    @property
    def command(self) -> str:
        return "vgs"

    @property
    def can_install(self) -> bool:
        return True

    def get_vg_info(
        self,
        vg_name: Optional[str] = None,
        options: str = "",
        sudo: bool = True,
    ) -> str:
        """
        Get volume group information.
        
        Args:
            vg_name: Optional name of a specific volume group
            options: Additional options to pass to vgs (e.g., "-o+devices", "--noheadings")
            sudo: Whether to run with sudo (default: True)
        
        Returns:
            The output from the vgs command
        """
        cmd_parts = ["vgs"]
        if options:
            cmd_parts.append(options)
        if vg_name:
            cmd_parts.append(vg_name)
        
        result = self.node.execute(" ".join(cmd_parts), sudo=sudo, expected_exit_code=0)
        return result.stdout

    def list_all_vgs(self, sudo: bool = True) -> str:
        """
        List all volume groups.
        
        Args:
            sudo: Whether to run with sudo (default: True)
        
        Returns:
            The output from the vgs command
        """
        result = self.node.execute("vgs", sudo=sudo, expected_exit_code=0)
        return result.stdout

    def vg_exists(self, vg_name: str, sudo: bool = True) -> bool:
        """
        Check if a volume group exists.
        
        Args:
            vg_name: Name of the volume group to check
            sudo: Whether to run with sudo (default: True)
        
        Returns:
            True if the volume group exists, False otherwise
        """
        result = self.node.execute(
            f"vgs {vg_name}",
            sudo=sudo,
            no_error_log=True
        )
        return result.exit_code == 0

    def _install(self) -> bool:
        self.node.os.install_packages("lvm2")
        return self._check_exists()
