# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePosixPath
from typing import List, Optional

from lisa.executable import Tool
from lisa.operating_system import Alpine, CBLMariner, CoreOs, Debian, Fedora, Oracle, Redhat, Suse, Ubuntu
from lisa.tools import Echo, Mkdir, Mount, Rm, Service
from lisa.util import LisaException, UnsupportedDistroException


class SmbServer(Tool):
    @property
    def command(self) -> str:
        return ""

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        # Install samba server and client utilities
        if isinstance(self.node.os, Ubuntu):
            self.node.os.install_packages(["samba", "samba-common-bin", "cifs-utils"])
        elif isinstance(self.node.os, Alpine):
            self.node.os.install_packages(["samba", "samba-client"])
        else:
            self.node.os.install_packages(["samba", "cifs-utils"])

        return self._check_exists()

    def _check_exists(self) -> bool:
        # Check if samba services exist
        service = self.node.tools[Service]
        return service.check_service_exists("smbd") and service.check_service_exists("nmbd")

    def create_share(
        self, 
        share_name: str, 
        share_path: str, 
        workgroup: str = "WORKGROUP",
        server_string: str = "LISA SMB Test Server"
    ) -> None:
        """Configure SMB server and create a share."""
        # Create share directory
        self.node.execute(f"mkdir -p {share_path}", sudo=True)
        self.node.execute(f"chmod 777 {share_path}", sudo=True)

        # Create SMB configuration
        smb_config = f"""
[global]
    workgroup = {workgroup}
    server string = {server_string}
    security = user
    map to guest = bad user
    dns proxy = no

[{share_name}]
    path = {share_path}
    browsable = yes
    writable = yes
    guest ok = yes
    read only = no
    create mask = 0755
"""

        # Write SMB configuration
        echo = self.node.tools[Echo]
        echo.write_to_file(
            smb_config, PurePosixPath("/etc/samba/smb.conf"), sudo=True
        )

        # Start SMB services
        self.start()

    def start(self) -> None:
        """Start SMB services (smbd and nmbd)."""
        service = self.node.tools[Service]
        service.restart_service("smbd")
        service.restart_service("nmbd")

        # Ensure services are running
        if not service.is_service_running("smbd"):
            raise LisaException("Failed to start SMB server (smbd)")
        if not service.is_service_running("nmbd"):
            raise LisaException("Failed to start SMB server (nmbd)")

    def stop(self) -> None:
        """Stop SMB services (smbd and nmbd)."""
        service = self.node.tools[Service]
        service.stop_service("smbd")
        service.stop_service("nmbd")

    def is_running(self) -> bool:
        """Check if SMB services are running."""
        service = self.node.tools[Service]
        return (
            service.is_service_running("smbd") and 
            service.is_service_running("nmbd")
        )

    def remove_share(self, share_path: str) -> None:
        """Remove a SMB share and its directory."""
        rm = self.node.tools[Rm]
        rm.remove_directory(share_path, sudo=True)


class SmbClient(Tool):
    @property
    def command(self) -> str:
        return ""

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        if isinstance(self.node.os, Ubuntu):
            # Install client utilities
            self.node.os.install_packages(["cifs-utils"])
        elif isinstance(self.node.os, Debian):
            # Debian-based distributions
            self.node.os.install_packages(["cifs-utils"])
        elif isinstance(self.node.os, (Fedora, Oracle)):
            # RedHat family (Fedora, RHEL, CentOS, Oracle, AlmaLinux, etc.)
            self.node.os.install_packages(["cifs-utils"])
        elif isinstance(self.node.os, CBLMariner):
            # Azure Linux/CBL-Mariner
            self.node.os.install_packages(["cifs-utils"])
        elif isinstance(self.node.os, Suse):
            # SUSE/openSUSE distributions
            self.node.os.install_packages(["cifs-utils"])
        elif isinstance(self.node.os, Alpine):
            # Alpine Linux
            self.node.os.install_packages(["cifs-utils"])
        elif isinstance(self.node.os, CoreOs):
            # CoreOS (limited package management)
            raise UnsupportedDistroException(
                self.node.os, "CoreOS does not support traditional package installation"
            )
        else:
            # Fallback for other distributions - try common package names
            try:
                self.node.os.install_packages(["cifs-utils"])
            except Exception as e:
                raise UnsupportedDistroException(
                    self.node.os, 
                    f"CIFS client packages installation failed: {e}. "
                    "Please install cifs-utils manually."
                )
        
        return self._check_exists()

    def _check_exists(self) -> bool:
        # Check if mount.cifs exists
        result = self.node.execute("which mount.cifs", sudo=True)
        return result.exit_code == 0

    def mount_share(
        self,
        server_address: str,
        share_name: str,
        mount_point: str,
        smb_version: str = "3.0",
        username: Optional[str] = None,
        password: Optional[str] = None,
        options: Optional[List[str]] = None,
    ) -> None:
        """Mount SMB share on client node with specified SMB version."""
        # Create mount point using Mkdir tool
        mkdir = self.node.tools[Mkdir]
        mkdir.create_directory(mount_point, sudo=True)

        # Build mount options
        mount_options = [f"vers={smb_version}", "file_mode=0777", "dir_mode=0777"]
        
        if username and password:
            mount_options.extend([f"username={username}", f"password={password}"])
        else:
            mount_options.append("guest")
        
        if options:
            mount_options.extend(options)

        # Mount SMB share
        mount_cmd = (
            f"mount -t cifs //{server_address}/{share_name} {mount_point} "
            f"-o {','.join(mount_options)}"
        )

        result = self.node.execute(mount_cmd, sudo=True)
        if result.exit_code != 0:
            raise LisaException(
                f"Failed to mount SMB share with version {smb_version}: {result.stderr}"
            )

    def unmount_share(self, mount_point: str) -> None:
        """Unmount SMB share."""
        mount = self.node.tools[Mount]
        mount.umount(point=mount_point, disk_name="", erase=False)

    def is_mounted(self, mount_point: str) -> bool:
        """Check if mount point exists and is mounted."""
        mount = self.node.tools[Mount]
        return mount.check_mount_point_exist(mount_point)

    def cleanup_mount_point(self, mount_point: str) -> None:
        """Remove mount point directory."""
        rm = self.node.tools[Rm]
        rm.remove_directory(mount_point, sudo=True)