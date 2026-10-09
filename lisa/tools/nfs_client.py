# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import ipaddress
import re

from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Debian, Redhat, Suse
from lisa.tools import Firewall, Mount
from lisa.tools.mkfs import FileSystem
from lisa.tools.rm import Rm
from lisa.util import SkippedException, UnsupportedDistroException

from .kernel_config import KernelConfig

_IPV6_ADDRESS_PATTERN = re.compile(r"[0-9a-fA-F:.%]+")


def _is_ipv6_address(address: str) -> bool:
    if ":" not in address or not _IPV6_ADDRESS_PATTERN.fullmatch(address):
        return False
    try:
        return ipaddress.ip_address(address).version == 6
    except ValueError:
        return False


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
        if _is_ipv6_address(server_ip):
            # NFS source syntax brackets IPv6 literals, e.g.
            # 2001:db8::5:/share becomes [2001:db8::5]:/share.
            server_address = f"[{server_ip}]"
            option_items = options.split(",") if options else []
            protocol = "tcp6"
            for index, option in enumerate(option_items):
                name, separator, value = option.partition("=")
                if name in ("proto", "mountproto") and separator:
                    if value in ("tcp", "udp"):
                        # Select the IPv6 netid: proto=tcp becomes proto=tcp6.
                        value = f"{value}6"
                    if name == "proto":
                        protocol = value
                    option_items[index] = f"{name}={value}"
            if not any(item.startswith("proto=") for item in option_items):
                option_items.append(f"proto={protocol}")
            # NFSv3 uses a separate mountd connection; NFSv4 does not.
            if "vers=3" in option_items and not any(
                item.startswith("mountproto=") for item in option_items
            ):
                option_items.append(f"mountproto={protocol}")
            options = ",".join(option_items)
        else:
            server_address = server_ip
        self.node.tools[Mount].mount(
            name=f"{server_address}:{server_shared_dir}",
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
