# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

from lisa.executable import Tool
from lisa.operating_system import BSD, Posix
from lisa.util import LisaException, find_groups_in_lines, find_patterns_groups_in_lines


def _get_size_in_bytes(size: float, size_unit: str) -> int:
    if size_unit == "T":
        return int(size * 1024 * 1024 * 1024 * 1024)
    if size_unit == "G":
        return int(size * 1024 * 1024 * 1024)
    elif size_unit == "M":
        return int(size * 1024 * 1024)
    elif size_unit == "K":
        return int(size * 1024)
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
    uuid: str = ""
    part_uuid: str = ""
    logical_devices: List["PartitionInfo"] = field(default_factory=list)

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
        uuid: str = "",
        part_uuid: str = "",
        logical_devices: Optional[List["PartitionInfo"]] = None,
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
        self.uuid = uuid
        self.part_uuid = part_uuid
        self.logical_devices = logical_devices if logical_devices else []


@dataclass
class DiskInfo(object):
    name: str = ""
    mountpoint: str = ""
    size_in_gb: int = 0
    type: str = ""
    fstype: str = ""
    partitions: List[PartitionInfo] = field(default_factory=list)
    uuid: str = ""

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
            partition.mountpoint.startswith("/boot")
            for partition in self.partitions
            if partition.mountpoint
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
        fstype: str = "",
        partitions: Optional[List[PartitionInfo]] = None,
        uuid: str = "",
    ):
        self.name = name
        self.mountpoint = mountpoint
        self.size_in_gb = int(size / (1024 * 1024 * 1024))
        self.type = dev_type
        self.fstype = fstype
        self.partitions = partitions if partitions else []
        self.uuid = uuid


class Lsblk(Tool):
    _INVAILD_JSON_OPTION_PATTERN = re.compile(r"lsblk: invalid option -- 'J'", re.M)
    # NAME="sdb1" SIZE="15030288384" TYPE="part" MOUNTPOINT="/mnt" FSTYPE="ext4"
    # UUID="ec9b6d68-0376-4284-b758-67aa37c47da5" PARTUUID="" PKNAME="sdb"
    _LSBLK_ENTRY_REGEX = re.compile(
        r'NAME="(?P<name>\S+)"\s+SIZE="(?P<size>\d+)"\s+'
        r'TYPE="(?P<type>\S+)"\s+MOUNTPOINT="(?P<mountpoint>\S*)"'
        r'\s+FSTYPE="(?P<fstype>\S*)"\s+UUID="(?P<uuid>\S*)"\s+PARTUUID='
        r'"(?P<partuuid>\S*)"\s+PKNAME="(?P<pkname>\S*)"'
    )

    # NAME="sdb1"
    _DISK_NAME_REGEX = re.compile(r'NAME="(?P<name>\S+)"')

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

    def _parse_partition(self, entry: Dict[str, Any]) -> PartitionInfo:
        return PartitionInfo(
            name=entry["name"],
            mountpoint=entry["mountpoint"],
            size=int(entry["size"]),
            dev_type=entry["type"],
            fstype=entry["fstype"],
            uuid=entry["uuid"],
            part_uuid=entry["partuuid"],
            logical_devices=[
                self._parse_partition(sub_child)
                for sub_child in entry.get("children", [])
            ],
        )

    def parse_lsblk_json_output(self, output: str) -> List[DiskInfo]:
        disks: List[DiskInfo] = []
        lsblk_entries = json.loads(output)["blockdevices"]
        for lsblk_entry in lsblk_entries:
            disk_mountpoint = lsblk_entry["mountpoint"]
            if disk_mountpoint == "/mnt/wslg/distro":
                # WSL mounts the system disk to /mnt/wslg/distro, and it's not
                # the default returned by lsblk. WSLg distro mountpoint is not
                # accessible, so replace it to "/"
                disk_mountpoint = "/"

            disk_info = DiskInfo(
                name=lsblk_entry["name"],
                mountpoint=disk_mountpoint,
                size=int(lsblk_entry["size"]),
                dev_type=lsblk_entry["type"],
                fstype=lsblk_entry["fstype"],
                uuid=lsblk_entry["uuid"],
            )

            for child in lsblk_entry.get("children", []):
                disk_info.partitions.append(self._parse_partition(child))
            # add disk to list of disks
            disks.append(disk_info)
        return disks

    def parse_lsblk_raw_output(self, output: str) -> List[DiskInfo]:
        disks: List[DiskInfo] = []
        lsblk_entries = find_patterns_groups_in_lines(
            output, [self._LSBLK_ENTRY_REGEX]
        )[0]

        logical_types = {"lvm", "crypt", "dm", "loop", "rom", "mpath", "md", "raid"}
        logical_devices_map: Dict[str, List[PartitionInfo]] = defaultdict(list)
        disk_partition_map: Dict[str, List[PartitionInfo]] = defaultdict(list)

        for entry in lsblk_entries:
            part = PartitionInfo(
                name=entry["name"],
                size=int(entry["size"]),
                dev_type=entry["type"],
                mountpoint=entry["mountpoint"],
                fstype=entry["fstype"],
                uuid=entry["uuid"],
                part_uuid=entry["partuuid"],
            )
            if entry["type"] in logical_types:
                logical_devices_map[entry["pkname"]].append(part)
            elif entry["type"] == "part":
                disk_partition_map[entry["pkname"]].append(part)
            elif entry["type"] == "disk":
                disks.append(
                    DiskInfo(
                        name=entry["name"],
                        mountpoint=entry["mountpoint"],
                        size=int(entry["size"]),
                        dev_type=entry["type"],
                        uuid=entry["uuid"],
                    )
                )

        # Add logical devices to the partition
        for part_list in disk_partition_map.values():
            for part in part_list:
                part.logical_devices = logical_devices_map.get(part.name, [])

        # Add partitions to the disk
        for disk in disks:
            disk.partitions = disk_partition_map.get(disk.name, [])

        return disks

    def get_disks(self, force_run: bool = False) -> List[DiskInfo]:
        disks: List[DiskInfo] = []

        # parse output of lsblk
        # -b print SIZE in bytes rather than in human readable format
        # -J output in JSON format
        # -o list of columns to output
        # -e exclude devices by major number, '-e 7' excludes loop devices
        cmd_result = self.run(
            "-e 7 -b -J -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE,UUID,PARTUUID",
            sudo=True,
            force_run=force_run,
        )
        output = cmd_result.stdout
        if cmd_result.exit_code != 0 and re.match(
            self._INVAILD_JSON_OPTION_PATTERN, output
        ):
            output = self.run(
                "-e 7 -b -P -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE,UUID,PARTUUID,PKNAME",
                sudo=True,
                force_run=force_run,
            ).stdout
            disks = self.parse_lsblk_raw_output(output)
        else:
            disks = self.parse_lsblk_json_output(output)

        # sort disk with OS disk first
        disks.sort(key=lambda disk: disk.is_os_disk, reverse=True)

        return disks

    def get_block_name(self, device: str, force_run: bool = False) -> str:
        # $ lsblk /dev/sda2 -P -o NAME
        # NAME="sda2"
        # NAME="vg-data"
        # NAME="vg-meta"
        # If there are logical volumes under sda2, the output will have multiple lines.
        # This function just get the device name sda2.
        result = self.run(f"{device} -P -o NAME", sudo=True, force_run=force_run)
        if result.exit_code == 0:
            lsblk_entries = find_patterns_groups_in_lines(
                result.stdout, [self._DISK_NAME_REGEX]
            )[0]
            for entry in lsblk_entries:
                return entry["name"]
        return ""

    def find_disk_by_mountpoint(
        self, mountpoint: str, force_run: bool = False
    ) -> DiskInfo:
        disks = self.get_disks(force_run=force_run)
        for disk in disks:
            # check if disk is mounted and mountpoint matches
            if disk.mountpoint == mountpoint:
                return disk

            # check if any of the partitions is mounted and mountpoint matches
            for partition in disk.partitions:
                for logical_device in partition.logical_devices:
                    if logical_device.mountpoint == mountpoint:
                        return disk
                if partition.mountpoint == mountpoint:
                    return disk

        raise LisaException(f"Could not find disk with mountpoint {mountpoint}")

    def find_partition_by_mountpoint(
        self, mountpoint: str, force_run: bool = False
    ) -> PartitionInfo:
        disk = self.find_disk_by_mountpoint(mountpoint, force_run=force_run)

        for partition in disk.partitions:
            if partition.mountpoint == mountpoint:
                return partition

        raise LisaException(f"Could not find partition with mountpoint {mountpoint}")

    def find_mountpoint_by_volume_name(
        self, volume_name: str, force_run: bool = False
    ) -> str:
        disks = self.get_disks(force_run=force_run)
        for disk in disks:
            # check if disk is mounted and mountpoint matches
            if disk.name == volume_name:
                return disk.mountpoint

            # check if any of the partitions is mounted and mountpoint matches
            for partition in disk.partitions:
                if partition.name == volume_name:
                    return partition.mountpoint

        raise LisaException(f"Could not find volume with name {volume_name}")


class BSDLsblk(Lsblk):
    # da1p1          0:103  12G freebsd-ufs                                       - /mnt/resource   # noqa: E501
    # nvd0             0:79  1.7T -                  diskid/DISK-a35fc877165000000001 - # noqa: E501
    _ENTRY_REGEX = re.compile(
        r"\s*(?P<name>\S+)\s+\d+:\d+\s+(?P<size>\d+|\d+.\d+)(?P<size_unit>\w+)\s+"
        r"(?P<type>\S+)\s+(?P<label>\S+)\s+(?P<mountpoint>\S*)"
    )

    # Example:
    # da1
    # nvd0
    _DISK_NAME_REGEX_MATCH = re.compile(r"^(da|nvd)\d+$")

    # Example:
    # da1p1
    # nvd0p1
    _PARTITION_NAME_REGEX_MATCH = re.compile(r"^(da|nvd)\d+p\d+$")

    # Example:
    # da1p1 -> da1
    # nvd0p1 -> nvd0
    _PARTITION_DISK_NAME_REGEX = re.compile(r"^(?P<disk_name>(da|nvd)\d+)p\d+$")

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
        output = self.run(force_run=force_run).stdout
        entries = find_groups_in_lines(output, self._ENTRY_REGEX)
        # create partition map to store partitions for each disk
        disk_partition_map: Dict[str, List[PartitionInfo]] = {}

        # get partitions for each disk
        for entry in entries:
            entry_name = entry["name"]
            if not self._PARTITION_NAME_REGEX_MATCH.match(entry_name):
                continue

            # extract drive name from partition name
            matched = find_groups_in_lines(
                entry["name"], self._PARTITION_DISK_NAME_REGEX
            )

            assert len(matched) == 1, "Could not extract drive name from partition name"
            drive_name = matched[0]["disk_name"]

            # convert size to bytes
            size_in_bytes = _get_size_in_bytes(float(entry["size"]), entry["size_unit"])

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
            size_in_bytes = _get_size_in_bytes(float(entry["size"]), entry["size_unit"])
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

    def get_block_name(self, device: str, force_run: bool = False) -> str:
        return device
