# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from lisa.executable import Tool
from lisa.util import LisaException, find_patterns_groups_in_lines


@dataclass
class PartitionInfo(object):
    name: str = ""
    mountpoint: str = ""
    size_in_gb: int = 0
    type: str = ""
    available_blocks: int = 0
    used_blocks: int = 0
    total_blocks: int = 0
    percentage_blocks_used: int = 0
    fstype: str = ""

    @property
    def is_mounted(self) -> bool:
        # check if mountpoint is set
        if self.mountpoint:
            return True

        return False

    @property
    def device_name(self) -> str:
        return f"/dev/{self.name}"

    def __init__(
        self,
        name: str,
        mountpoint: str,
        size: int = 0,
        type: str = "",
        available_blocks: int = 0,
        used_blocks: int = 0,
        total_blocks: int = 0,
        percentage_blocks_used: int = 0,
        fstype: str = "",
    ):
        self.name = name
        self.mountpoint = mountpoint
        self.size_in_gb = int(size / (1024 * 1024 * 1024))
        self.type = type
        self.available_blocks = available_blocks
        self.used_blocks = used_blocks
        self.total_blocks = total_blocks
        self.percentage_blocks_used = percentage_blocks_used
        self.fstype = fstype


@dataclass
class DiskInfo(object):
    name: str = ""
    mountpoint: str = ""
    size_in_gb: int = 0
    type: str = ""
    partitions: List[PartitionInfo] = field(default_factory=list)

    @property
    def is_os_disk(self) -> bool:
        # check if the disk contains boot partition
        # boot partitions start with /boot/{id}
        for partition in self.partitions:
            if partition.mountpoint.startswith("/boot"):
                return True
        return False

    @property
    def is_mounted(self) -> bool:
        # check if the disk or any of its partitions are mounted
        if self.mountpoint:
            return True

        for partition in self.partitions:
            if partition.mountpoint:
                return True

        return False

    @property
    def device_name(self) -> str:
        return f"/dev/{self.name}"

    def __init__(
        self,
        name: str,
        mountpoint: str,
        size: int = 0,
        type: str = "",
        partitions: Optional[List[PartitionInfo]] = None,
    ):
        self.name = name
        self.mountpoint = mountpoint
        self.size_in_gb = int(size / (1024 * 1024 * 1024))
        self.type = type
        self.partitions = partitions if partitions is not None else []


class Lsblk(Tool):
    # NAME="loop2" SIZE="34017280" TYPE="loop" MOUNTPOINT="/snap/snapd/13640"
    _LSBLK_ENTRY_REGEX = re.compile(
        r'NAME="(?P<name>\S+)"\s+SIZE="(?P<size>\d+)"\s+'
        r'TYPE="(?P<type>\S+)"\s+MOUNTPOINT="(?P<mountpoint>\S*)"'
        r'\s+FSTYPE="(?P<fstype>\S*)"'
    )

    # sda
    _DISK_NAME_REGEX = re.compile(r"\s*(?P<name>\D+)\s*")

    @property
    def command(self) -> str:
        return "lsblk"

    def get_disks(self, force_run: bool = False) -> List[DiskInfo]:
        disks: List[DiskInfo] = []

        # parse output of lsblk
        output = self.run(
            "-b -P -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE", sudo=True, force_run=force_run
        ).stdout
        lsblk_entries = find_patterns_groups_in_lines(
            output, [self._LSBLK_ENTRY_REGEX]
        )[0]

        # create partition map
        disk_partition_map: Dict[str, List[PartitionInfo]] = {}
        for lsblk_entry in lsblk_entries:
            # we only need to add partitions to the map
            if not lsblk_entry["type"] == "part":
                continue

            # extract drive name from partition name
            matched = find_patterns_groups_in_lines(
                lsblk_entry["name"], [self._DISK_NAME_REGEX]
            )[0]
            assert len(matched) == 1, "Could not extract drive name from partition name"

            # add partition to disk partition map
            drive_name = matched[0]["name"]
            if drive_name not in disk_partition_map:
                disk_partition_map[drive_name] = []

            disk_partition_map[drive_name].append(
                PartitionInfo(
                    name=lsblk_entry["name"],
                    size=int(lsblk_entry["size"]),
                    type=lsblk_entry["type"],
                    mountpoint=lsblk_entry["mountpoint"],
                    fstype=lsblk_entry["fstype"],
                )
            )

        # create disk info
        for lsblk_entry in lsblk_entries:
            # we only add physical disks to the list
            if not lsblk_entry["type"] == "disk":
                continue

            # add disk to list of disks
            disks.append(
                DiskInfo(
                    name=lsblk_entry["name"],
                    mountpoint=lsblk_entry["mountpoint"],
                    size=int(lsblk_entry["size"]),
                    type=lsblk_entry["type"],
                    partitions=disk_partition_map.get(lsblk_entry["name"], []),
                )
            )

        return disks

    def find_disk_by_mountpoint(
        self, mountpoint: str, force_run: bool = False
    ) -> DiskInfo:
        disks = self.get_disks(force_run=force_run)
        for disk in disks:
            # check if disk is mounted and moutpoint matches
            if disk.mountpoint == mountpoint:
                return disk

            # check if any of the partitions is mounted and moutpoint matches
            for partition in disk.partitions:
                if partition.mountpoint == mountpoint:
                    return disk

        raise LisaException(f"Could not find disk with mountpoint {mountpoint}")

    def find_mountpoint_by_volume_name(
        self, volume_name: str, force_run: bool = False
    ) -> str:
        disks = self.get_disks(force_run=force_run)
        for disk in disks:
            # check if disk is mounted and moutpoint matches
            if disk.name == volume_name:
                return disk.mountpoint

            # check if any of the partitions is mounted and moutpoint matches
            for partition in disk.partitions:
                if partition.name == volume_name:
                    return partition.mountpoint

        raise LisaException(f"Could not find volume with name {volume_name}")
