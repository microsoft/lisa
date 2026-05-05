# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from enum import Enum
from typing import Optional, Type, cast

from lisa.executable import Tool
from lisa.operating_system import Posix, Suse
from lisa.util import LisaException, find_patterns_groups_in_lines, get_matched_str

FileSystem = Enum(
    "mkfs",
    [
        "xfs",
        "cifs",
        "ext2",
        "ext3",
        "ext4",
        "btrfs",
        "debugfs",
        "hugetlbfs",
        "nfs",
        "tracefs",
        "ufs",
    ],
)

BSD_FILE_SYSTEM_MAP = {
    FileSystem.ufs: "freebsd-ufs",
}


class Mkfs(Tool):
    __EXIST_FILE_SYSTEM_PATTERN = re.compile(
        r".*appears to contain an existing filesystem", re.MULTILINE
    )

    @property
    def command(self) -> str:
        return "mkfs.xfs"

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return BSDMkfs

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


class BSDMkfs(Mkfs):
    # /dev/da0p1
    # /dev/nvd0p1
    _PARTITION_ID_REGEX = re.compile(r"^(?P<disk>/dev/(da|nvd)\d+)p(?P<index>\d+)$")

    @property
    def command(self) -> str:
        return "newfs"

    def format_disk(self, disk_name: str, file_system: FileSystem) -> None:
        self._create_partition_with_filesystem(disk_name, file_system)
        if file_system == FileSystem.ufs:
            self.node.execute(
                f"newfs -U {disk_name}",
                shell=True,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=f"fail to format disk {disk_name}",
            )
        else:
            raise LisaException(
                f"Support for formatting file system {file_system} not implemented"
            )

    def _create_partition_with_filesystem(
        self, partition: str, file_system: FileSystem
    ) -> None:
        # get partition id and disk
        matched = find_patterns_groups_in_lines(partition, [self._PARTITION_ID_REGEX])[
            0
        ]
        assert len(matched) == 1, "no match found for partition index"
        partition_id = matched[0]["index"]
        disk_name = matched[0]["disk_name"]
        file_system_mapped = BSD_FILE_SYSTEM_MAP[file_system]

        # delete the partition
        self.node.execute(
            f"gpart delete -i {partition_id} {disk_name}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"fail to delete partition {partition_id} on disk {disk_name}"
            ),
        )

        # create partition with given filesystem
        self.node.execute(
            f"gpart add -t {file_system_mapped} -i {partition_id} {disk_name}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"fail to create partition {partition_id} on disk {disk_name}"
            ),
        )
