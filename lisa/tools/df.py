# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import List, Optional

from lisa.executable import Tool
from lisa.tools.lsblk import PartitionInfo
from lisa.util import find_patterns_groups_in_lines


class Df(Tool):
    # Filesystem                1K-blocks  Used Available Use% Mounted on
    # /dev/mapper/rootvg-homelv   1038336 40472    997864   4% /home
    _DF_ENTRY_REGEX = re.compile(
        r"(?P<name>\S+)\s+(?P<total>\d+)\s+(?P<used>\d+)\s+"
        r"(?P<available>\d+)\s+(?P<percentage_use>\d+)%\s+(?P<mountpoint>\S+)"
    )

    @property
    def command(self) -> str:
        return "df"

    @property
    def can_install(self) -> bool:
        return True

    def get_partitions(self, force_run: bool = False) -> List[PartitionInfo]:
        # run df and parse the output
        # The output is in the following format:
        # <Filesystem> <1K-blocks> <Used> <Available> <Use%> <Mounted on>
        # Note : <Used> and <Available> are in 1-k blocks, not in bytes
        output = self.run(sudo=True, force_run=force_run).stdout
        partition_info = []
        df_entries = find_patterns_groups_in_lines(output, [self._DF_ENTRY_REGEX])[0]
        for df_entry in df_entries:
            partition_info.append(
                PartitionInfo(
                    name=df_entry["name"],
                    mountpoint=df_entry["mountpoint"],
                    available_blocks=int(df_entry["available"]),
                    used_blocks=int(df_entry["used"]),
                    total_blocks=int(df_entry["total"]),
                    percentage_blocks_used=int(df_entry["percentage_use"]),
                )
            )
        return partition_info

    def get_partition_by_mountpoint(
        self, mountpoint: str, force_run: bool = False
    ) -> Optional[PartitionInfo]:
        # get `df` entry for the partition with the given mountpoint
        df_partition_info = self.get_partitions(force_run)
        for partition in df_partition_info:
            if partition.mountpoint == mountpoint:
                return partition
        return None

    def get_filesystem_available_space(
        self, path: str = ".", force_run: bool = False
    ) -> float:
        # return the input 'path' available space in GB by running df
        # If 'path' doesn't exist, return 0
        # The df cmd output is in the following format:
        # <Filesystem> <1K-blocks> <Used> <Available> <Use%> <Mounted on>
        # Note : <Available> are in 1-k blocks, not in bytes
        available_space = 0.0
        out = self.run(parameters=path, sudo=True, force_run=force_run).stdout

        df_entries = find_patterns_groups_in_lines(out, [self._DF_ENTRY_REGEX])[0]
        if len(df_entries) == 0:  # path not exist
            self._log.debug(f"Path: {path} not exist! return 0 available space.")
            return 0.0

        available_space = (float)(df_entries[0]["available"]) / 1024**2
        return available_space
