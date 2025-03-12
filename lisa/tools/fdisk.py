# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import List, Optional, Pattern, Type, cast

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools.mkfs import BSD_FILE_SYSTEM_MAP, FileSystem, Mkfs
from lisa.util import LisaException, find_patterns_in_lines


class Fdisk(Tool):
    # fdisk: invalid option -- 'w'
    not_support_option_pattern = re.compile(r"fdisk: invalid option -- 'w'.*", re.M)

    LIST_PARTITION_COMMAND = (
        "sync; ls -lt /dev/sd*; ls -lt /dev/nvme*; ls -lt /dev/xvd*"
    )

    @property
    def command(self) -> str:
        return "fdisk"

    @property
    def can_install(self) -> bool:
        return True

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return BSDFdisk

    def make_partition(
        self,
        disk_name: str,
        file_system: FileSystem = FileSystem.ext4,
        format_: bool = True,
        first_partition_size: str = "",
        second_partition_size: str = "",
    ) -> str:
        """
        disk_name: make a partition against the disk.
        file_system: making the file system type against the partition.
        format: format the disk into specified file system type.
        Make a partition and a filesystem against the disk.
        """
        # n => new a partition
        # p => primary partition
        # 1 => Partition number
        # "" => Use default 2048 for 'First sector'
        # "" => Use default 2147483647 as 'Last sector'
        # w => write table to disk and exit
        # in case that the disk/disk partition has been formatted previously
        # fdisk -w always => always to wipe signatures
        # fdisk -W always => always to wipe signatures from new partitions
        mkfs = self.node.tools[Mkfs]
        cmd_result = self.node.execute(
            f"(echo n; echo p; echo 1; echo '{first_partition_size}';"
            f" echo '{second_partition_size}'; echo w) |"
            f" {self.command} -w always -W always {disk_name}",
            shell=True,
            sudo=True,
        )
        # remove '-w' and '-W' options
        # when lower fdisk version doesn't support
        if self.not_support_option_pattern.match(cmd_result.stdout):
            self.node.execute(
                f"(echo n; echo p; echo 1; echo '{first_partition_size}';"
                f" echo '{second_partition_size}'; echo w) |"
                f" {self.command} {disk_name}",
                shell=True,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=f"fail to format disk {disk_name}.",
            )
        # get the partition, e.g. /dev/sdc1 or /dev/nvme0n1p1
        partition_disk = self._get_partitions(disk_name)
        if not partition_disk:
            raise LisaException(
                f"fail to find partition(s) after formatting disk {disk_name}"
            )
        if format_:
            mkfs.format_disk(partition_disk[0], file_system)
        return partition_disk[0]

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
        partition_pattern = self._get_partition_pattern(disk_name)
        cmd_result = self.node.execute(
            self.LIST_PARTITION_COMMAND,
            shell=True,
            sudo=True,
        )
        matched = find_patterns_in_lines(cmd_result.stdout, [partition_pattern])
        return matched[0]

    def _get_partition_pattern(self, disk_name: str) -> Pattern[str]:
        return re.compile(rf"({disk_name}p[0-9]|{disk_name}[0-9])+")


class BSDFdisk(Fdisk):
    LIST_PARTITION_COMMAND = "sync; ls -lt /dev/da*; ls -lt /dev/nvd*"

    @property
    def can_install(self) -> bool:
        return False

    def _check_exists(self) -> bool:
        return True

    def _get_partition_pattern(self, disk_name: str) -> Pattern[str]:
        return re.compile(rf"({disk_name}p[0-9]+)")

    def delete_partitions(self, disk_name: str) -> None:
        result = self.node.execute(
            f"gpart destroy -F {disk_name}",
            shell=True,
            sudo=True,
        )

        if result.exit_code != 0 and "Invalid argument" not in result.stdout:
            raise LisaException(f"fail to delete partitions for disk {disk_name}")

    def make_partition(
        self,
        disk_name: str,
        file_system: FileSystem = FileSystem.ufs,
        format_: bool = True,
        first_partition_size: str = "",
        second_partition_size: str = "",
    ) -> str:
        # add free space to the end of the disk
        self.node.execute(
            f"gpart create -s gpt {disk_name}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"fail to create gpt partition table for disk {disk_name}."
            ),
        )

        # add a partition using the whole disk
        file_system_mapped = BSD_FILE_SYSTEM_MAP[file_system]
        self.node.execute(
            f"gpart add -t {file_system_mapped} {disk_name}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"fail to add partition for disk {disk_name}."
            ),
        )

        # get the partition, e.g. /dev/sdc1 or /dev/nvme0n1p1
        partition_disk = self._get_partitions(disk_name)
        if not partition_disk:
            raise LisaException(
                f"fail to find partition(s) after formatting disk {disk_name}"
            )

        if format_:
            mkfs = self.node.tools[Mkfs]
            mkfs.format_disk(partition_disk[0], file_system)

        return partition_disk[0]
