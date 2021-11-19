# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import dataclass
from typing import List, Optional

from lisa.executable import Tool
from lisa.util import find_patterns_in_lines


@dataclass
class PartitionInfo(Tool):
    partition_name: str = ""
    blocks: int = 0
    used: int = 0
    total_size: int = 0
    percentage_used: int = 0
    mountpoint: str = ""

    def __init__(
        self,
        partition_name: str,
        blocks: int,
        used: int,
        total_size: int,
        percentage_used: int,
        mountpoint: str,
    ):
        self.partition_name = partition_name
        self.blocks = blocks
        self.used = used
        self.total_size = total_size
        self.percentage_used = percentage_used
        self.mountpoint = mountpoint


class Df(Tool):
    # devtmpfs         4071644       0   4071644   0% /dev
    _DF_ENTRY_REGEX = re.compile(
        r"(?P<name>\S+)\s+(?P<blocks>\d+)\s+(?P<used>\d+)\s+"
        r"(?P<total>\d+)\s+(?P<percentage_use>\d+)%\s+(?P<mountpoint>\S+)"
    )

    @property
    def command(self) -> str:
        return "df"

    def can_install(self) -> bool:
        return True

    def get_partition_information(self) -> List[PartitionInfo]:
        # run df and parse the output
        # The output is in the following format:
        # <Filesystem> <1K-blocks> <Used> <Available> <Use%> <Mounted on>
        # Note : <Used> and <Available> are in 1-k blocks, not in bytes
        output = self.run(sudo=True).stdout
        partition_info = []
        df_entries = find_patterns_in_lines(output, [self._DF_ENTRY_REGEX])[0]
        for df_entry in df_entries:
            partition_info.append(
                PartitionInfo(
                    partition_name=df_entry[0],
                    blocks=int(df_entry[1]),
                    used=int(df_entry[2]),
                    total_size=int(df_entry[3]),
                    percentage_used=int(df_entry[4]),
                    mountpoint=df_entry[5],
                )
            )
        return partition_info

    def get_partition_with_mountpoint(
        self, partition_mountpoint: str
    ) -> Optional[PartitionInfo]:
        # get `df` entry for the partition with the given mountpoint
        df_partition_info = self.get_partition_information()
        for partition in df_partition_info:
            if partition.mountpoint == partition_mountpoint:
                return partition
        return None
