# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import List, Optional, cast

from assertpy.assertpy import assert_that
from retry import retry

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools import Fdisk
from lisa.tools.mkfs import FileSystem, Mkfs
from lisa.util import LisaException


@dataclass
class PartitionInfo(object):
    # TODO: Merge with lsblk.PartitionInfo
    name: str
    disk: str
    mount_point: str
    type: str

    # /dev/sda1
    # /dev/sdc
    _disk_regex = re.compile(r"\s*\/dev\/(?P<disk>\D+).*")

    def __init__(self, name: str, mount_point: str, type: str) -> None:
        self.name = name
        self.mount_point = mount_point
        self.type = type
        matched = self._disk_regex.fullmatch(name)
        assert matched
        self.disk = matched.group("disk")

    def __str__(self) -> str:
        return self.__repr__()

    def __repr__(self) -> str:
        return (
            f"name: {self.name}, "
            f"disk: {self.disk}, "
            f"mount_point: {self.mount_point}, "
            f"type: {self.type}"
        )


class Mount(Tool):
    _DEFAULT_TYPE = FileSystem.ext4
    # umount: nvme0n1: not mounted.
    __UMOUNT_ERROR_PATTERN = re.compile(
        r".*(mountpoint not found|no mount point specified|not mounted)", re.MULTILINE
    )

    # /dev/sda1 on / type ext4 (rw,relatime,discard)
    # /dev/sda1 on /mnt/a type ext4 (rw,relatime,discard)
    _partition_info_regex = re.compile(
        r"\s*/dev/(?P<name>.*)\s+on\s+(?P<mount_point>.*)\s+type\s+(?P<type>.*)\s+.*"
    )

    @property
    def command(self) -> str:
        return "mount"

    @property
    def can_install(self) -> bool:
        return True

    @retry(tries=10, delay=5)
    def mount(
        self,
        name: str,
        point: str,
        type: Optional[FileSystem] = None,
        options: str = "",
        format: bool = False,
    ) -> None:
        self.node.shell.mkdir(PurePosixPath(point), exist_ok=True)
        runline = [self.command]
        if type:
            runline.append(f"-t {type.name}")
        if options:
            runline.append(f"-o {options}")
        if format:
            format_type = type if type else self._DEFAULT_TYPE
            self.node.tools[Mkfs].format_disk(name, format_type)
        runline.append(f"{name} {point}")
        cmd_result = self.node.execute(" ".join(runline), shell=True, sudo=True)
        cmd_result.assert_exit_code()

    def umount(
        self, disk_name: str, point: str, erase: bool = True, type: str = ""
    ) -> None:
        if type:
            type = f"-t {type}"
        cmd_result = self.node.execute(f"umount {type} {point}", shell=True, sudo=True)
        if erase:
            fdisk = self.node.tools[Fdisk]
            fdisk.delete_partitions(disk_name)
            self.node.execute(f"rm -r {point}", shell=True, sudo=True)
        if (
            not self.__UMOUNT_ERROR_PATTERN.match(cmd_result.stdout)
            and 0 != cmd_result.exit_code
        ):
            raise LisaException(f"Fail to umount {point}: {cmd_result.stdout}")

    def get_partition_info(self) -> List[PartitionInfo]:
        # partition entries in the output are of the form
        # /dev/<name> on <mount_point> type <type>
        # Example:
        # /dev/sda1 on / type ext4
        output: str = self.run(force_run=True).stdout
        partition_info: List[PartitionInfo] = []
        for line in output.splitlines():
            matched = self._partition_info_regex.fullmatch(line)
            if matched:
                partition_name = matched.group("name")
                partition_info.append(
                    PartitionInfo(
                        f"/dev/{partition_name}",
                        matched.group("mount_point"),
                        matched.group("type"),
                    )
                )

        self._log.debug(f"Found disk partitions : {partition_info}")
        return partition_info

    def get_mount_point_for_partition(self, partition_name: str) -> Optional[str]:
        partition_info = self.get_partition_info()
        matched_partitions = [
            partition
            for partition in partition_info
            if partition.name == partition_name
        ]

        if len(matched_partitions) == 0:
            return None

        assert_that(
            matched_partitions,
            f"Exactly one partition with name {partition_name} should be present",
        ).is_length(1)
        partition = matched_partitions[0]
        self._log.debug(f"disk: {partition}, mount_point: {partition.mount_point}")

        return partition.mount_point

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("util-linux")
        return self._check_exists()
