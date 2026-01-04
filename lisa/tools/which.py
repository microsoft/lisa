# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool


class Which(Tool):
    @property
    def command(self) -> str:
        return "which"

    @property
    def can_install(self) -> bool:
        return False

    def _check_exists(self) -> bool:
        return True

    def find_command(self, command_name: str, sudo: bool = False) -> str:
        """
        Find the full path of a command using 'which'.

        Args:
            command_name: Name of the command to find
            sudo: Whether to run with sudo privileges

        Returns:
            Full path to the command if found, empty string if not found
        """
        result = self.run(
            command_name,
            sudo=sudo,
            force_run=True,
            no_error_log=True,
        )

        if result.exit_code == 0:
            return result.stdout.strip()
        return ""

    def check_command_exists(self, command_name: str, sudo: bool = False) -> bool:
        """
        Check if a command exists in the system PATH.

        Args:
            command_name: Name of the command to check
            sudo: Whether to run with sudo privileges

        Returns:
            True if command exists, False otherwise
        """
        return bool(self.find_command(command_name, sudo=sudo))
