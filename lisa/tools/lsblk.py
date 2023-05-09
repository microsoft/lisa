# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Type

from lisa.executable import Tool
from lisa.operating_system import BSD, Posix
from lisa.util import LisaException, find_patterns_groups_in_lines


def _get_size_in_bytes(size: int, size_unit: str) -> int:
    if size_unit == "G":
        return size * 1024 * 1024 * 1024
    elif size_unit == "M":
        return size * 1024 * 1024
    elif size_unit == "K":
        return size * 1024
    else:
        raise LisaException(f"Unknown size unit {size_unit}")


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
        dev_type: str = "",
        available_blocks: int = 0,
        used_blocks: int = 0,
        total_blocks: int = 0,
        percentage_blocks_used: int = 0,
        fstype: str = "",
    ):
        self.name = name
        self.mountpoint = mountpoint
        self.size_in_gb = int(size / (1024 * 1024 * 1024))
        self.type = dev_type
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
        # check if mountpoint is set
        # WSL does not have a boot partition in the lsblk output
        # so we check for the home directory instead
        if self.mountpoint == "/":
            return True

        # check if the disk contains boot partition
        # boot partitions start with /boot/{id}
        return any(
            partition.mountpoint.startswith("/boot") for partition in self.partitions
        )

    @property
    def is_mounted(self) -> bool:
        # check if the disk or any of its partitions are mounted
        if self.mountpoint:
            return True

        return any(partition.mountpoint for partition in self.partitions)

    @property
    def device_name(self) -> str:
        return f"/dev/{self.name}"

    def __init__(
        self,
        name: str,
        mountpoint: str,
        size: int = 0,
        dev_type: str = "",
        partitions: Optional[List[PartitionInfo]] = None,
    ):
        self.name = name
        self.mountpoint = mountpoint
        self.size_in_gb = int(size / (1024 * 1024 * 1024))
        self.type = dev_type
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

    @property
    def can_install(self) -> bool:
        return True

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return BSDLsblk

    def _install(self) -> bool:
        if isinstance(self.node.os, Posix):
            self.node.os.install_packages("util-linux")
        else:
            raise LisaException(
                f"tool {self.command} can't be installed in distro {self.node.os.name}."
            )
        return self._check_exists()

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
                    dev_type=lsblk_entry["type"],
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
                    dev_type=lsblk_entry["type"],
                    partitions=disk_partition_map.get(lsblk_entry["name"], []),
                )
            )

        # sort disk with OS disk first
        disks.sort(key=lambda disk: disk.is_os_disk, reverse=True)

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


class BSDLsblk(Lsblk):
    # da1p1          0:103  12G freebsd-ufs                                       - /mnt/resource   # noqa: E501
    _ENTRY_REGEX = re.compile(
        r"\s*(?P<name>\S+)\s+\d+:\d+\s+(?P<size>\d+)(?P<size_unit>\w+)\s+"
        r"(?P<type>\S+)\s+(?P<label>\S+)\s+(?P<mountpoint>\S*)"
    )

    # Example:
    # da1
    _DISK_NAME_REGEX_MATCH = re.compile(r"^\D+\d*$")

    # Example:
    # da1p1
    _PARTITION_NAME_REGEX_MATCH = re.compile(r"^\D+\d+\D*\d+$")

    _PARTITION_DISK_NAME_REGEX = re.compile(r"^(?P<disk_name>\D+\d+)\D+\d+$")

    @property
    def command(self) -> str:
        return "lsblk"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        assert isinstance(self.node.os, BSD)
        self.node.os.install_packages("lsblk")
        return self._check_exists()

    def get_disks(self, force_run: bool = False) -> List[DiskInfo]:
        disks: List[DiskInfo] = []

        # parse output of lsblk
        output = self.run().stdout
        entries = find_patterns_groups_in_lines(output, [self._ENTRY_REGEX])[0]

        # create partition map to store partitions for each disk
        disk_partition_map: Dict[str, List[PartitionInfo]] = {}

        # get partitions for each disk
        for entry in entries:
            entry_name = entry["name"]
            if not self._PARTITION_NAME_REGEX_MATCH.match(entry_name):
                continue

            # extract drive name from partition name
            matched = find_patterns_groups_in_lines(
                entry["name"], [self._PARTITION_DISK_NAME_REGEX]
            )[0]
            assert len(matched) == 1, "Could not extract drive name from partition name"
            drive_name = matched[0]["disk_name"]

            # convert size to bytes
            size_in_bytes = _get_size_in_bytes(int(entry["size"]), entry["size_unit"])

            # add partition to disk partition map
            if drive_name not in disk_partition_map:
                disk_partition_map[drive_name] = []
            disk_partition_map[drive_name].append(
                PartitionInfo(
                    name=entry["name"],
                    size=size_in_bytes,
                    mountpoint=entry["mountpoint"],
                    fstype=entry["type"],
                )
            )

        # get disk info
        for entry in entries:
            entry_name = entry["name"]
            if not self._DISK_NAME_REGEX_MATCH.match(entry_name):
                continue

            # convert size to bytes and create disk info
            size_in_bytes = _get_size_in_bytes(int(entry["size"]), entry["size_unit"])
            disks.append(
                DiskInfo(
                    name=entry["name"],
                    mountpoint=entry["mountpoint"],
                    size=size_in_bytes,
                    dev_type=entry["type"],
                    partitions=disk_partition_map.get(entry["name"], []),
                )
            )

        # sort disk with OS disk first
        disks.sort(key=lambda disk: disk.is_os_disk, reverse=True)
        return disks
