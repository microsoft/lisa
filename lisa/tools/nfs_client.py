# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Debian, Redhat, Suse
from lisa.tools import Firewall, Mount
from lisa.tools.mkfs import FileSystem
from lisa.tools.rm import Rm
from lisa.util import SkippedException, UnsupportedDistroException

from .kernel_config import KernelConfig


class NFSClient(Tool):
    @property
    def command(self) -> str:
        return "/sbin/mount.nfs"

    @property
    def can_install(self) -> bool:
        return True

    def setup(
        self,
        server_ip: str,
        server_shared_dir: str,
        mount_dir: str,
        options: str = "",
    ) -> None:
        # skip test if protocol is udp and CONFIG_NFS_DISABLE_UDP_SUPPORT is
        # set in kernel
        # https://bugs.launchpad.net/ubuntu/+source/linux/+bug/1964093
        if "udp" in options:
            if self.node.tools[KernelConfig].is_built_in(
                "CONFIG_NFS_DISABLE_UDP_SUPPORT"
            ):
                raise SkippedException("NFS udp support is disabled in kernel")

        # stop firewall
        self.node.tools[Firewall].stop()

        # mount server shared directory
        self.node.tools[Mount].mount(
            name=f"{server_ip}:{server_shared_dir}",
            point=mount_dir,
            fs_type=FileSystem.nfs,
            options=options,
        )

    def stop(self, mount_dir: str) -> None:
        self.node.execute(f"umount -lf {mount_dir}", sudo=True)
        self.node.tools[Rm].remove_directory(mount_dir, sudo=True)

    def _install(self) -> bool:
        if isinstance(self.node.os, Redhat) or isinstance(self.node.os, CBLMariner):
            self.node.os.install_packages("nfs-utils")
        elif isinstance(self.node.os, Debian):
            self.node.os.install_packages("nfs-common")
        elif isinstance(self.node.os, Suse):
            pass
        else:
            raise UnsupportedDistroException(self.node.os)

        return self._check_exists()
