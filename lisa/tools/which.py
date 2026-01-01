# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Optional

from lisa.executable import Tool


class Which(Tool):
    @property
    def command(self) -> str:
        return "which"

    @property
    def can_install(self) -> bool:
        return False

    def find_command(self, command_name: str, sudo: bool = False) -> Optional[str]:
        """
        Find the full path of a command.
        
        Args:
            command_name: The name of the command to find
            sudo: Whether to run with sudo privileges
            
        Returns:
            The full path to the command if found, None otherwise
        """
        result = self.run(
            command_name,
            force_run=True,
            sudo=sudo,
            shell=True,
        )
        
        if result.exit_code == 0:
            return result.stdout.strip()
        return None

    def command_exists(self, command_name: str, sudo: bool = False) -> bool:
        """
        Check if a command exists in the system PATH.
        
        Args:
            command_name: The name of the command to check
            sudo: Whether to run with sudo privileges
            
        Returns:
            True if the command exists, False otherwise
        """
        result = self.run(
            command_name,
            force_run=True,
            sudo=sudo,
            shell=True,
        )
        
        return result.exit_code == 0