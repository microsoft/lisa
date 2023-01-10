# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool
from lisa.tools.lsblk import Lsblk
from lisa.tools.rm import Rm


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
