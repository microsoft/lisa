# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePosixPath
from typing import Any, List, Optional

from lisa.executable import Tool
from lisa.operating_system import (
    Alpine,
    CBLMariner,
    CoreOs,
    Debian,
    Fedora,
    Oracle,
    Redhat,
    Suse,
    Ubuntu,
)
from lisa.tools import Chmod, Echo, Mkdir, Mount, Rm, Service
from lisa.tools.firewall import Firewall
from lisa.tools.mkfs import FileSystem
from lisa.util import UnsupportedDistroException


class SmbServer(Tool):
    SMB_CONF_FILE = "/etc/samba/smb.conf"
    
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        # Set service names based on distribution
        if isinstance(self.node.os, (CBLMariner, Redhat, Fedora, Oracle, Suse)):
            self._smb_service = "smb"
            self._nmb_service = "nmb"
        elif isinstance(self.node.os, Alpine):
            self._smb_service = "samba"
            self._nmb_service = "nmbd"
        else:
            # Default fallback
            self._smb_service = "smbd"
            self._nmb_service = "nmbd"

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
        elif isinstance(self.node.os, (Debian, CoreOs, Fedora, Oracle, Redhat, Suse)):
            self.node.os.install_packages(["samba", "cifs-utils"])
        else:
            raise UnsupportedDistroException(self.node.os)

        return self._check_exists()

    def _check_exists(self) -> bool:
        # Check if samba services exist
        service = self.node.tools[Service]
        return service.check_service_exists(
            self._smb_service
        ) and service.check_service_exists(self._nmb_service)

    def create_share(
        self,
        share_name: str,
        share_path: str,
        workgroup: str = "WORKGROUP",
        server_string: str = "LISA SMB Test Server",
    ) -> None:
        """Configure SMB server and create a share."""
        # Create share directory
        self.node.tools[Mkdir].create_directory(share_path, sudo=True)

        # Set permissions for the share directory
        self.node.tools[Chmod].chmod(share_path, "777", sudo=True)
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
        self.node.tools[Echo].write_to_file(
            smb_config, PurePosixPath(self.SMB_CONF_FILE), sudo=True
        )

        # Start SMB services
        self.start()

    def start(self) -> None:
        """Start SMB services."""
        service = self.node.tools[Service]
        service.restart_service(self._smb_service)
        service.restart_service(self._nmb_service)
        # stop firewall to allow SMB traffic
        self.node.tools[Firewall].stop()

    def stop(self) -> None:
        """Stop SMB services."""
        service = self.node.tools[Service]
        service.stop_service(self._smb_service)
        service.stop_service(self._nmb_service)

    def is_running(self) -> bool:
        """Check if SMB services are running."""
        service = self.node.tools[Service]
        return service.is_service_running(
            self._smb_service
        ) and service.is_service_running(self._nmb_service)

    def remove_share(self, share_path: str) -> None:
        """Remove a SMB share and its directory."""
        self.node.tools[Rm].remove_directory(share_path, sudo=True)


class SmbClient(Tool):
    @property
    def command(self) -> str:
        return "mount.cifs"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        # Install client utilities
        if isinstance(
            self.node.os,
            (Ubuntu, Debian, CBLMariner, CoreOs, Fedora, Oracle, Redhat, Suse, Alpine),
        ):
            self.node.os.install_packages(["cifs-utils"])
        else:
            raise UnsupportedDistroException(self.node.os)
        return self._check_exists()

    def mount_share(
        self,
        server_address: str,
        share_name: str,
        mount_point: str,
        smb_version: str = "3.0",
        options: Optional[List[str]] = None,
    ) -> None:
        """Mount SMB share on client node with specified SMB version."""
        # Create mount point
        self.node.tools[Mkdir].create_directory(mount_point, sudo=True)

        # Build mount options
        mount_options = [
            f"vers={smb_version}",
            "file_mode=0777",
            "dir_mode=0777",
            "guest",
        ]

        if options:
            mount_options.extend(options)

        # Mount SMB share
        self.node.tools[Mount].mount(
            point=mount_point,
            name=f"//{server_address}/{share_name}",
            fs_type=FileSystem.cifs,
            options=",".join(mount_options),
            format_=False,
        )

    def unmount_share(self, mount_point: str) -> None:
        """Unmount SMB share."""
        self.node.tools[Mount].umount(point=mount_point, disk_name="", erase=False)

    def is_mounted(self, mount_point: str) -> bool:
        """Check if mount point exists and is mounted."""
        return self.node.tools[Mount].check_mount_point_exist(mount_point)

    def cleanup_mount_point(self, mount_point: str) -> None:
        """Remove mount point directory."""
        self.node.tools[Rm].remove_directory(mount_point, sudo=True)
