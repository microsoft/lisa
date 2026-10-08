# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.base_tools import Service
from lisa.operating_system import Debian, OperatingSystem, Redhat, Suse
from lisa.tools.mkfs import FileSystem
from lisa.tools.mount import Mount
from lisa.tools.nfs_client import NFSClient
from lisa.util import LisaException, UnsupportedDistroException


class AzNfs(NFSClient):
    """Mount Azure Files NFSv4.1 shares through a local TLS tunnel."""

    # The v3 watchdog does not cover the NFSv4.1 TLS path.
    WATCHDOG_SERVICE = "aznfswatchdogv4"

    @property
    def command(self) -> str:
        return "/sbin/mount.aznfs"

    @classmethod
    def is_supported(cls, os: OperatingSystem) -> bool:
        """Check whether aznfs is published for this distribution."""
        return isinstance(os, (Debian, Redhat, Suse))

    def _install(self) -> bool:
        super()._install()
        env_prefix = "AZNFS_NONINTERACTIVE_INSTALL=1"
        packages_config_path = (
            '$(source /etc/os-release && echo "$ID/${VERSION_ID%%.*}")'
        )
        if isinstance(self.node.os, Debian):
            env_prefix += " DEBIAN_FRONTEND=noninteractive"
            # Debian repositories use the full VERSION_ID.
            install_script = (
                "curl -sSL -O https://packages.microsoft.com/config/"
                '$(source /etc/os-release && echo "$ID/$VERSION_ID")'
                "/packages-microsoft-prod.deb && "
                "dpkg -i packages-microsoft-prod.deb && "
                "rm -f packages-microsoft-prod.deb && "
                "apt-get update && "
                "apt-get install -y aznfs"
            )
        elif isinstance(self.node.os, Suse):
            install_script = (
                "curl -sSL -O https://packages.microsoft.com/config/"
                f"{packages_config_path}"
                "/packages-microsoft-prod.rpm && "
                "rpm -i packages-microsoft-prod.rpm && "
                "rm -f packages-microsoft-prod.rpm && "
                "zypper --non-interactive refresh && "
                "zypper --non-interactive install aznfs"
            )
        elif isinstance(self.node.os, Redhat):
            install_script = (
                "curl -sSL -O https://packages.microsoft.com/config/"
                f"{packages_config_path}"
                "/packages-microsoft-prod.rpm && "
                "rpm -i packages-microsoft-prod.rpm && "
                "rm -f packages-microsoft-prod.rpm && "
                "yum install -y aznfs"
            )
        else:
            raise UnsupportedDistroException(
                self.node.os,
                "aznfs install is not implemented here. Use nfs_mount_helper "
                "'nfs', or run on Ubuntu/Debian, RHEL, or SUSE.",
            )

        result = self.node.execute(
            f"{env_prefix} bash -c '{install_script}'",
            sudo=True,
            shell=True,
            timeout=300,
        )
        result.assert_exit_code(0, "aznfs install failed.", include_output=True)
        self._log.debug("aznfs installed from the Microsoft package repo.")
        return self._check_exists()

    def _ensure_watchdog(self) -> None:
        service = self.node.tools[Service]
        if service.is_service_running(self.WATCHDOG_SERVICE):
            return
        service.enable_service(self.WATCHDOG_SERVICE)
        service.start_service(self.WATCHDOG_SERVICE)
        if not service.is_service_running(self.WATCHDOG_SERVICE):
            raise LisaException(
                f"aznfs is installed but {self.WATCHDOG_SERVICE} is not active, "
                "so every NFSv4.1 aznfs mount will fail. Check "
                f"'systemctl status {self.WATCHDOG_SERVICE}' on the node."
            )

    @property
    def fstype(self) -> str:
        return str(FileSystem.aznfs.name)

    def setup(
        self,
        server_ip: str,
        server_shared_dir: str,
        mount_dir: str,
        options: str = "",
    ) -> None:
        self._ensure_watchdog()

        self.node.tools[Mount].mount(
            name=f"{server_ip}:{server_shared_dir}",
            point=mount_dir,
            fs_type=FileSystem.aznfs,
            options=options,
        )

    def get_mount_source(self, mount_dir: str) -> str:
        """Return the loopback source recorded for the aznfs mount."""
        source_result = self.node.execute(
            f"findmnt --noheadings --output SOURCE --mountpoint {mount_dir}",
            sudo=True,
        )
        source_result.assert_exit_code(
            0,
            f"aznfs mounted {mount_dir}, but its kernel mount source could "
            "not be resolved.",
            include_output=True,
        )
        rows = source_result.stdout.split()
        # A leftover overmount might be listed before the current source.
        source = rows[-1] if rows else ""
        if not source:
            raise LisaException(
                f"aznfs mounted {mount_dir}, but findmnt returned an empty "
                "source for it."
            )
        return source
