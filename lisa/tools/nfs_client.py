# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool
from lisa.operating_system import SLES, Debian, Redhat
from lisa.tools import Firewall, Mount
from lisa.util import UnsupportedDistroException


class NFSClient(Tool):
    @property
    def command(self) -> str:
        return "/sbin/mount.nfs"

    def can_install(self) -> bool:
        return True

    def setup(
        self,
        server_ip: str,
        server_shared_dir: str,
        mount_dir: str,
        protocol: str = "tcp",
    ) -> None:
        # stop firewall
        self.node.tools[Firewall].stop()

        # mount server shared directory
        self.node.tools[Mount].mount(
            disk_name=f"{server_ip}:{server_shared_dir}",
            point=mount_dir,
            type="nfs",
            options=f"proto={protocol},vers=3",
        )

    def _install(self) -> bool:
        if isinstance(self.node.os, Redhat):
            self.node.os.install_packages("nfs-utils")
        elif isinstance(self.node.os, Debian):
            self.node.os.install_packages("nfs-common")
        elif isinstance(self.node.os, SLES):
            pass
        else:
            raise UnsupportedDistroException(self.node.os)

        return self._check_exists()
