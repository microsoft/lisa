# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Optional

from lisa.executable import Tool


class Dmsetup(Tool):
    @property
    def command(self) -> str:
        return "dmsetup"

    @property
    def can_install(self) -> bool:
        return True

    def status(self, device_name: str, sudo: bool = True) -> str:
        """
        Get the status of a device mapper device.
        
        Args:
            device_name: Name of the device mapper device
            sudo: Whether to run with sudo (default: True)
        
        Returns:
            The status output
        """
        result = self.node.execute(
            f"dmsetup status {device_name}",
            sudo=sudo,
            expected_exit_code=0
        )
        return result.stdout

    def table(self, device_name: str, sudo: bool = True) -> str:
        """
        Get the table of a device mapper device.
        
        Args:
            device_name: Name of the device mapper device
            sudo: Whether to run with sudo (default: True)
        
        Returns:
            The table output
        """
        result = self.node.execute(
            f"dmsetup table {device_name}",
            sudo=sudo,
            expected_exit_code=0
        )
        return result.stdout

    def info(self, device_name: Optional[str] = None, sudo: bool = True) -> str:
        """
        Get information about device mapper devices.
        
        Args:
            device_name: Optional name of a specific device mapper device
            sudo: Whether to run with sudo (default: True)
        
        Returns:
            The info output
        """
        cmd = "dmsetup info"
        if device_name:
            cmd += f" {device_name}"
        
        result = self.node.execute(cmd, sudo=sudo, expected_exit_code=0)
        return result.stdout

    def ls(self, sudo: bool = True) -> str:
        """
        List all device mapper devices.
        
        Args:
            sudo: Whether to run with sudo (default: True)
        
        Returns:
            The list of devices
        """
        result = self.node.execute("dmsetup ls", sudo=sudo, expected_exit_code=0)
        return result.stdout

    def message(
        self,
        device_name: str,
        sector: str,
        message: str,
        sudo: bool = True,
    ) -> str:
        """
        Send a message to a device mapper device.
        
        Args:
            device_name: Name of the device mapper device
            sector: Sector number
            message: Message to send
            sudo: Whether to run with sudo (default: True)
        
        Returns:
            The command output
        """
        result = self.node.execute(
            f"dmsetup message {device_name} {sector} {message}",
            sudo=sudo,
            expected_exit_code=0
        )
        return result.stdout

    def _install(self) -> bool:
        # dmsetup is typically part of the device-mapper package
        self.node.os.install_packages("device-mapper")
        return self._check_exists()
