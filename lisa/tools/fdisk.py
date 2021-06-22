# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from enum import Enum
from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import LisaException

from .mkfs import Mkfsext, Mkfsxfs

FileSystem = Enum(
    "mkfs",
    ["xfs", "ext2", "ext3", "ext4"],
)


class Fdisk(Tool):
    @property
    def command(self) -> str:
        return "fdisk"

    @property
    def can_install(self) -> bool:
        return True

    def make_partition(self, disk_name: str, file_system: FileSystem) -> None:
        """
        disk_name: make a partition against the disk.
        file_system: making the file system type against the partition
        Make a partition and a filesystem against the disk.
        """
        # n => new a partition
        # p => primary partition
        # 1 => Partition number
        # "" => Use default 2048 for 'First sector'
        # "" => Use default 2147483647 as 'Last sector'
        # w => write table to disk and exit
        self.node.execute(
            f"(echo n; echo p; echo 1; echo ; echo; echo ; echo w) | "
            f"{self.command} {disk_name}",
            shell=True,
            sudo=True,
        )
        if file_system == FileSystem.xfs:
            mkfs_xfs = self.node.tools[Mkfsxfs]
            mkfs_xfs.mkfs(f"{disk_name}p1", str(file_system))
        elif file_system in [FileSystem.ext2, FileSystem.ext3, FileSystem.ext4]:
            mkfs_ext = self.node.tools[Mkfsext]
            mkfs_ext.mkfs(f"{disk_name}p1", str(file_system))
        else:
            raise LisaException(f"Unrecognized file system {file_system}.")

    def delete_partition(self, disk_name: str) -> None:
        """
        disk: delete one partition against the disk.
        Delete the only partition of this disk.
        """
        # d => delete a partition
        # w => write table to disk and exit
        self.node.execute(
            f"(echo d; echo w) | {self.command} {disk_name}", shell=True, sudo=True
        )

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("util-linux")
        return self._check_exists()
