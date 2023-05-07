# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from enum import Enum
from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix, Suse
from lisa.util import LisaException, get_matched_str

FileSystem = Enum(
    "mkfs",
    ["xfs", "ext2", "ext3", "ext4", "btrfs", "hugetlbfs", "nfs", "tracefs"],
)


class Mkfs(Tool):
    __EXIST_FILE_SYSTEM_PATTERN = re.compile(
        r".*appears to contain an existing filesystem", re.MULTILINE
    )

    @property
    def command(self) -> str:
        return "mkfs.xfs"

    @property
    def can_install(self) -> bool:
        return True

    # command - mkfs.xfs, mkfs.ext2, mkfs.ext3, mkfs.ext4
    def mkfs(self, disk: str, file_system: FileSystem) -> None:
        cmd_result = self.node.execute(
            f"echo y | {file_system} {disk}", shell=True, sudo=True
        )
        if get_matched_str(cmd_result.stdout, self.__EXIST_FILE_SYSTEM_PATTERN):
            cmd_result = self.node.execute(
                f"echo y | {file_system} -f {disk}", shell=True, sudo=True
            )
        cmd_result.assert_exit_code()

    def format_disk(self, disk_name: str, file_system: FileSystem) -> None:
        if file_system == FileSystem.xfs:
            mkfs_xfs = self.node.tools[Mkfsxfs]
            mkfs_xfs.mkfs(disk_name, file_system)
        elif file_system in [FileSystem.ext2, FileSystem.ext3, FileSystem.ext4]:
            mkfs_ext = self.node.tools[Mkfsext]
            mkfs_ext.mkfs(disk_name, file_system)
        elif file_system in [FileSystem.btrfs]:
            mkfs_btrfs = self.node.tools[Mkfsbtrfs]
            mkfs_btrfs.mkfs(disk_name, file_system)
        else:
            raise LisaException(f"Unrecognized file system {file_system}.")

    def _install(self) -> bool:
        # the installation is completed in format_disk based on file_system
        return True


class Mkfsxfs(Mkfs):
    @property
    def command(self) -> str:
        return "mkfs.xfs"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("xfsprogs")
        return self._check_exists()


class Mkfsext(Mkfs):
    @property
    def command(self) -> str:
        return "mkfs.ext4"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("e2fsprogs")
        return self._check_exists()


class Mkfsbtrfs(Mkfs):
    @property
    def command(self) -> str:
        return "mkfs.btrfs"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        package = "btrfs-progs"
        if isinstance(self.node.os, Suse):
            package = "btrfsprogs"
        posix_os.install_packages(package)
        return self._check_exists()
