# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import Optional, Type

from lisa.executable import Tool
from lisa.tools.lsblk import Lsblk
from lisa.tools.rm import Rm
from lisa.util import find_patterns_in_lines


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
