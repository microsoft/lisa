# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Dict, List, Optional, cast

from assertpy.assertpy import assert_that
from retry import retry

from lisa.executable import Tool
from lisa.operating_system import BSD, Posix
from lisa.tools import Fdisk
from lisa.tools.mkfs import FileSystem, Mkfs
from lisa.util import LisaException, find_groups_in_lines


@dataclass
class PartitionInfo(object):
    # TODO: Merge with lsblk.PartitionInfo
    name: str
    disk: str
    mount_point: str
    type: str
    options: List[str]
    # /dev/sda1
    # /dev/sdc
    _disk_regex = re.compile(r"\s*\/dev\/(?P<disk>\D+).*")

    def __init__(
        self, name: str, mount_point: str, fs_type: str, options: Optional[List[str]]
    ) -> None:
        self.name = name
        self.mount_point = mount_point
        self.type = fs_type
        matched = self._disk_regex.fullmatch(name)
        assert matched
        self.disk = matched.group("disk")
        if options:
            self.options = options
        else:
            self.options = []

    def __str__(self) -> str:
        return self.__repr__()

    def __repr__(self) -> str:
        return (
            f"name: {self.name}, "
            f"disk: {self.disk}, "
            f"mount_point: {self.mount_point}, "
            f"type: {self.type}, "
            f"options: {','.join(self.options)}"
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
        r"\s*/dev/(?P<name>.*)\s+on\s+(?P<mount_point>.*)\s+type"
        r"\s+(?P<type>.*)\s+\(?(?P<options>.*)\)?"
    )
    _mount_info_regex = re.compile(
        r"\s*(?P<name>.*)\s+on\s+(?P<mount_point>.*)\s+type\s+(?P<type>.*)\s\(+.*"
    )

    # /dev/da1p1 on /mnt/resource (ufs, local, soft-updates)
    # zroot/ROOT/default on / (zfs, local, nfsv4acls)
    _partition_info_regex_bsd = re.compile(
        r"\s*(?:\/dev\/|zroot\/)(?P<name>.*)\s+on\s+(?P<mount_point>.*?)\s+"
        r"(\((?P<type>.*),(?P<options>.*)\))"
    )

    @property
    def command(self) -> str:
        return "mount"

    @property
    def can_install(self) -> bool:
        return True

    @retry(tries=24, delay=5)  # type: ignore
    def mount(
        self,
        name: str,
        point: str,
        fs_type: Optional[FileSystem] = None,
        options: str = "",
        format_: bool = False,
    ) -> None:
        self.node.shell.mkdir(PurePosixPath(point), exist_ok=True)
        runline = [self.command]
        if fs_type:
            runline.append(f"-t {fs_type.name}")
        if options:
            runline.append(f"-o {options}")
        if format_:
            format_type = fs_type or self._DEFAULT_TYPE
            self.node.tools[Mkfs].format_disk(name, format_type)
        runline.append(f"{name} {point}")
        cmd_result = self.node.execute(" ".join(runline), shell=True, sudo=True)
        cmd_result.assert_exit_code()

    @retry(tries=24, delay=5)  # type: ignore
    def remount(
        self,
        point: str,
        options: List[str],
    ) -> None:
        runline = [self.command]
        if isinstance(self.node.os, BSD):
            # BSD allows updating mount options with -u flag
            # User must specify all options on the commandline
            runline.append("-u")
        else:
            # Linux 'mount' allows remounting using old mount options
            # ex: mount -o remount,exec /path
            # will remount path and replace noexec with exec, but keep other any options
            options = ["remount"] + options
        runline.append(f"-o {','.join(options)}")
        runline.append(f"{point}")
        cmd_result = self.node.execute(" ".join(runline), shell=True, sudo=True)
        cmd_result.assert_exit_code()

    def umount(
        self, disk_name: str, point: str, erase: bool = True, fs_type: str = ""
    ) -> None:
        if fs_type:
            fs_type = f"-t {fs_type}"
        cmd_result = self.node.execute(
            f"umount {fs_type} {point}", shell=True, sudo=True
        )
        if erase:
            fdisk = self.node.tools[Fdisk]
            fdisk.delete_partitions(disk_name)
            self.node.execute(f"rm -r {point}", shell=True, sudo=True)
        if (
            not self.__UMOUNT_ERROR_PATTERN.match(cmd_result.stdout)
            and 0 != cmd_result.exit_code
        ):
            raise LisaException(f"Fail to umount {point}: {cmd_result.stdout}")

    def get_partition_info(self, mountpoint: str = "") -> List[PartitionInfo]:
        # partition entries in the output are of the form
        # /dev/<name> on <mount_point> type <type>
        # Example:
        # /dev/sda1 on / type ext4
        output: str = self.run(force_run=True).stdout
        partition_info: List[PartitionInfo] = []
        for line in output.splitlines():
            if isinstance(self.node.os, BSD):
                matched = self._partition_info_regex_bsd.fullmatch(line)
            else:
                matched = self._partition_info_regex.fullmatch(line)
            if matched:
                partition_name = matched.group("name")
                option_match = matched.group("options")
                if not option_match:
                    options = []
                else:
                    split_options = option_match.split(",")
                    options = [option.strip() for option in split_options]
                partition_info.append(
                    PartitionInfo(
                        name=f"/dev/{partition_name}",
                        mount_point=matched.group("mount_point"),
                        fs_type=matched.group("type"),
                        options=options,
                    )
                )

        self._log.debug(f"Found disk partitions : {partition_info}")
        if mountpoint:
            return list(
                [
                    partition
                    for partition in partition_info
                    if partition.mount_point == mountpoint
                ]
            )
        else:
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

    def check_mount_point_exist(self, mount_point: str) -> bool:
        output: str = self.run(force_run=True).stdout
        mount_points: List[Dict[str, str]] = []
        mount_points = find_groups_in_lines(
            output, self._mount_info_regex, single_line=False
        )
        self._log.debug(f"Found mount points: {mount_points}")
        return any([x for x in mount_points if mount_point == x["mount_point"]])

    def reload_fstab_config(self) -> None:
        res = self.run("-a", force_run=True, sudo=True)
        if res.exit_code != 0:
            raise LisaException(
                f"Failed to reload fstab configuration file: {res.stdout}"
            )

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("util-linux")
        return self._check_exists()
