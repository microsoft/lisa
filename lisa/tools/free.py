# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool
from lisa.util import LisaException


class Free(Tool):
    @property
    def command(self) -> str:
        return "free"

    def get_swap_size(self) -> int:
        # Return total swap size
        # Example output:
        #         total used free
        # Swap:   0     0    0
        out = self.run("-m", force_run=True).stdout
        for line in out.splitlines():
            if line.startswith("Swap:"):
                return int(line.split()[1])

        raise LisaException("Failed to get swap size")
