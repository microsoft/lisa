# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import dataclass
from typing import List

from lisa.executable import Tool
from lisa.util import find_patterns_in_lines


@dataclass
class PartitionInfo(Tool):
    name: str = ""
    size: int = 0
    type: str = ""
    mountpoint: str = ""

    def __init__(self, name: str, size: int, type: str, mountpoint: str):
        self.name = name
        self.size = size
        self.type = type
        self.mountpoint = mountpoint


class Lsblk(Tool):
    # NAME="loop2" SIZE="34017280" TYPE="loop" MOUNTPOINT="/snap/snapd/13640"
    _LSBLK_ENTRY_REGEX = re.compile(
        r'NAME="(?P<name>\S+)"\s+SIZE="(?P<size>\d+)"\s+'
        r'TYPE="(?P<type>\S+)"\s+MOUNTPOINT="(?P<mountpoint>\S+)"'
    )

    @property
    def command(self) -> str:
        return "lsblk"

    def get_partition_information(self) -> List[PartitionInfo]:
        # parse output of lsblk
        output = self.run("-b -P -o NAME,SIZE,TYPE,MOUNTPOINT", sudo=True).stdout
        partition_info = []
        lsblk_entries = find_patterns_in_lines(output, [self._LSBLK_ENTRY_REGEX])[0]
        for lsblk_entry in lsblk_entries:
            partition_info.append(
                PartitionInfo(
                    name=lsblk_entry[0],
                    size=int(lsblk_entry[1]),
                    type=lsblk_entry[2],
                    mountpoint=lsblk_entry[3],
                )
            )
        return partition_info
