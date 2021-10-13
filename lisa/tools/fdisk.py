# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import List, cast

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import find_patterns_in_lines

from .mkfs import FileSystem, Mkfs


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
        mkfs = self.node.tools[Mkfs]
        self.node.execute(
            f"(echo n; echo p; echo 1; echo ; echo; echo ; echo w) | "
            f"{self.command} {disk_name}",
            shell=True,
            sudo=True,
        )
        # get the partition, e.g. /dev/sdc1 or /dev/nvme0n1p1
        partition_disk = self._get_partitions(disk_name)
        mkfs.format_disk(partition_disk[0], file_system)

    def delete_partitions(self, disk_name: str) -> None:
        """
        disk: delete all partitions against the disk.
        Get the partitions of this disk.
        Delete all partitions of this disk.
        """
        partitions = self._get_partitions(disk_name)
        for _ in range(1, len(partitions) + 1):
            # d => delete a partition
            # w => write table to disk and exit
            self.node.execute(
                f"(echo d; echo ; echo w) | {self.command} {disk_name}",
                shell=True,
                sudo=True,
            )

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("util-linux")
        return self._check_exists()

    def _get_partitions(self, disk_name: str) -> List[str]:
        partition_pattern = re.compile(rf"({disk_name}p[0-9]|{disk_name}[0-9])+")
        cmd_result = self.node.execute(
            "ls -lt /dev/sd* && ls -lt /dev/nvme*", shell=True, sudo=True
        )
        matched = find_patterns_in_lines(cmd_result.stdout, [partition_pattern])
        return matched[0]
