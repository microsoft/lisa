# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePosixPath
from typing import List

from lisa.executable import Tool
from lisa.operating_system import SLES, Debian, Redhat
from lisa.tools import Echo, Firewall
from lisa.tools.service import Service
from lisa.util import UnsupportedDistroException


class NFSServer(Tool):
    @property
    def command(self) -> str:
        return ""

    @property
    def can_install(self) -> bool:
        return True

    def create_shared_dir(self, client_ips: List[str], dir_name: str) -> None:
        # create directory to share
        self.node.execute(f"chmod -R a+rwX {dir_name}", sudo=True)

        # clear /etc/export file to remove any previous exports
        self.node.tools[Echo].write_to_file(
            "", PurePosixPath("/etc/exports"), sudo=True
        )

        # add client ip to /etc/exports file
        for client_ip in client_ips:
            self.node.tools[Echo].write_to_file(
                f"{dir_name} {client_ip}(rw,sync,no_subtree_check)",
                PurePosixPath("/etc/exports"),
                sudo=True,
                append=True,
            )

        # stop firewall
        self.node.tools[Firewall].stop()

        # restart nfs service
        if isinstance(self.node.os, Redhat):
            self.node.tools[Service].restart_service(
                "nfs-server",
            )
        elif isinstance(self.node.os, Debian):
            self.node.tools[Service].restart_service(
                "nfs-kernel-server",
            )
        elif isinstance(self.node.os, SLES):
            self.node.tools[Service].restart_service(
                "nfsserver",
            )
        else:
            raise UnsupportedDistroException(self.node.os)

    def _install(self) -> bool:
        if isinstance(self.node.os, Redhat):
            self.node.os.install_packages("nfs-utils")
        elif isinstance(self.node.os, Debian):
            self.node.os.install_packages("nfs-kernel-server")
        elif isinstance(self.node.os, SLES):
            self.node.os.install_packages("nfs-kernel-server")
        else:
            raise UnsupportedDistroException(self.node.os)

        return self._check_exists()

    def _check_exists(self) -> bool:
        if isinstance(self.node.os, Redhat):
            return self.node.tools[Service].check_service_exists("nfs-utils")
        elif isinstance(self.node.os, Debian):
            return self.node.tools[Service].check_service_exists("nfs-kernel-server")
        elif isinstance(self.node.os, SLES):
            return self.node.tools[Service].check_service_exists("nfs-kernel-server")
        else:
            raise UnsupportedDistroException(self.node.os)
