# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import dataclass
from typing import List

from lisa.executable import Tool
from lisa.util import find_patterns_groups_in_lines


@dataclass
class PartitionInfo(object):
    name: str = ""
    mountpoint: str = ""
    size: int = 0
    type: str = ""
    available_blocks: int = 0
    used_blocks: int = 0
    total_blocks: int = 0
    percentage_blocks_used: int = 0

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
    ):
        self.name = name
        self.mountpoint = mountpoint
        self.size = size
        self.type = type
        self.available_blocks = available_blocks
        self.used_blocks = used_blocks
        self.total_blocks = total_blocks
        self.percentage_blocks_used = percentage_blocks_used


class Lsblk(Tool):
    # NAME="loop2" SIZE="34017280" TYPE="loop" MOUNTPOINT="/snap/snapd/13640"
    _LSBLK_ENTRY_REGEX = re.compile(
        r'NAME="(?P<name>\S+)"\s+SIZE="(?P<size>\d+)"\s+'
        r'TYPE="(?P<type>\S+)"\s+MOUNTPOINT="(?P<mountpoint>\S+)"'
    )

    @property
    def command(self) -> str:
        return "lsblk"

    def get_partitions(self, force_run: bool = False) -> List[PartitionInfo]:
        # parse output of lsblk
        output = self.run(
            "-b -P -o NAME,SIZE,TYPE,MOUNTPOINT", sudo=True, force_run=force_run
        ).stdout
        partition_info = []
        lsblk_entries = find_patterns_groups_in_lines(
            output, [self._LSBLK_ENTRY_REGEX]
        )[0]
        for lsblk_entry in lsblk_entries:
            partition_info.append(
                PartitionInfo(
                    name=lsblk_entry["name"],
                    size=int(lsblk_entry["size"]),
                    type=lsblk_entry["type"],
                    mountpoint=lsblk_entry["mountpoint"],
                )
            )
        return partition_info
