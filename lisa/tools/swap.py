# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from dataclasses import dataclass
from typing import List, Optional, Type

from lisa.base_tools import Cat
from lisa.executable import Tool
from lisa.tools.df import Df
from lisa.tools.lsblk import Lsblk
from lisa.tools.rm import Rm
from lisa.util import (
    LisaException,
    find_patterns_groups_in_lines,
    find_patterns_in_lines,
)


@dataclass
class SwapPartition(object):
    filename: str = ""
    type: str = ""
    partition: str = ""


class SwapOn(Tool):
    @property
    def command(self) -> str:
        return "swapon"


class SwapOff(Tool):
    @property
    def command(self) -> str:
        return "swapoff"


class MkSwap(Tool):
    @property
    def command(self) -> str:
        return "mkswap"


class Swap(Tool):
    # Filename       Type         Size      Used      Priority
    # /dev/sdb2      partition    1020      0          -2
    # /swapfile      file         200M     15M         -3
    # /mnt/swapfile  file         2097148   0          -4
    _SWAPS_PATTERN = re.compile(
        r"(?P<filename>\S+)\s+(?P<type>\S+)\s+(?P<size>\d+)\w?\s+(?P<used>\d+)\w?\s+(?P<priority>-?\d+)"  # noqa: E501
    )

    @property
    def command(self) -> str:
        raise NotImplementedError()

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return SwapInfoBSD

    def _check_exists(self) -> bool:
        return True

    def is_swap_enabled(self) -> bool:
        # swapon lists the swap files and partitions
        # example output:
        # /swapfile file 1024M 507.4M   -1
        swapon = self.node.tools[SwapOn].run("-s").stdout
        if "swap" in swapon:
            return True

        # lsblk lists swap partitions
        # example output:
        # sdb2   8:18   0   7.6G  0 part [SWAP]
        lsblk = self.node.tools[Lsblk].run().stdout
        return "SWAP" in lsblk

    def get_swap_partitions(self) -> List[SwapPartition]:
        # run 'cat /proc/swaps' or 'swapon -s' and parse the output
        # The output is in the following format:
        # <Filename> <Type> <Size> <Used> <Priority>
        # Filename       Type       Size     Used     Priority
        # /dev/dm-5      partition  3891196  1820932  -2
        # /mnt/swapfile  file       4194300  0        -3
        cat = self.node.tools[Cat]
        swap_result = cat.run("/proc/swaps", shell=True, sudo=True)
        if swap_result.exit_code != 0:
            # Try another way to get swap information
            swap_result = self.node.tools[SwapOn].run("-s")
            if swap_result.exit_code != 0:
                raise LisaException("Failed to get swap information")

        output = swap_result.stdout
        swap_parts: List[SwapPartition] = []
        swap_entries = find_patterns_groups_in_lines(output, [self._SWAPS_PATTERN])[0]
        for swap_entry in swap_entries:
            filename = swap_entry["filename"]
            file_type = swap_entry["type"]
            if file_type == "partition":
                partition = filename
            else:
                # For swap files, get the partition information
                part = self.node.tools[Df].get_partition_by_path(filename)
                if not part:
                    raise LisaException(
                        f"Failed to get partition information for {filename}"
                    )
                partition = part.name
            swap_parts.append(
                SwapPartition(filename=filename, type=file_type, partition=partition)
            )

        return swap_parts

    def create_swap(
        self, path: str = "/tmp/swap", size: str = "1M", count: int = 1024
    ) -> None:
        self.node.execute(f"dd if=/dev/zero of={path} bs={size} count={count}")
        self.node.tools[MkSwap].run(path, sudo=True, force_run=True)
        self.node.tools[SwapOn].run(path, sudo=True, force_run=True)

    def delete_swap(self, path: str = "/tmp/swap") -> None:
        self.node.tools[SwapOff].run(path, sudo=True, force_run=True)
        self.node.tools[Rm].remove_file(path, sudo=True)


class SwapInfoBSD(Swap):
    # Check the entries in the output of swapinfo -k
    # example output:
    # Device          1K-blocks     Used    Avail Capacity
    # /dev/da1p2        2097152        0  2097152     0%
    _SWAP_ENTRIES = re.compile(
        r"(?P<device>\S+)\s+(?P<blocks>\d+)\s+(?P<used>\d+)\s+(?P<avail>\d+)\s+(?P<capacity>\S+)"  # noqa: E501
    )

    @property
    def command(self) -> str:
        return "swapinfo"

    def is_swap_enabled(self) -> bool:
        entries = find_patterns_in_lines(self.run("-k").stdout, [self._SWAP_ENTRIES])
        if len(entries[0]) > 0:
            return True

        return False

    def get_swap_partitions(self) -> List[SwapPartition]:
        # run 'swapinfo -k' and parse the output
        # The output is in the following format:
        # <Device> <1K-blocks> <Used> <Avail> <Capacity>
        swap_result = self.run("-k")
        if swap_result.exit_code != 0:
            raise LisaException("Failed to get swap information")

        output = swap_result.stdout
        swap_parts: List[SwapPartition] = []
        swap_entries = find_patterns_groups_in_lines(output, [self._SWAP_ENTRIES])[0]
        # FreeBSD doesn't have swap files, only partitions
        for swap_entry in swap_entries:
            swap_parts.append(
                SwapPartition(
                    filename=swap_entry["device"],
                    type="partition",
                    partition=swap_entry["device"],
                )
            )
        return swap_parts
