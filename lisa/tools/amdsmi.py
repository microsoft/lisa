# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re

from lisa.executable import Tool
from lisa.util import LisaException, find_groups_in_lines


class AmdSmi(Tool):
    # Pattern to match GPU entries in amd-smi list output
    # Example:
    # GPU: 0
    #     BDF: N/A
    #     UUID: N/A
    #     KFD_ID: 65402
    #     NODE_ID: 2
    #     PARTITION_ID: 0
    _gpu_pattern = re.compile(r"^GPU:\s+\d+", re.MULTILINE)

    @property
    def command(self) -> str:
        return "amd-smi"

    @property
    def can_install(self) -> bool:
        return False

    def get_gpu_count(self) -> int:
        """
        Get the number of AMD GPUs detected by amd-smi.
        Uses 'amd-smi list' command which shows all GPU devices.
        """
        result = self.run("list")
        if result.exit_code != 0 or (result.exit_code == 0 and result.stdout == ""):
            result = self.run("list", sudo=True)
            if result.exit_code != 0 or (result.exit_code == 0 and result.stdout == ""):
                raise LisaException(
                    f"amd-smi command exited with exit_code {result.exit_code}"
                )

        gpu_matches = find_groups_in_lines(result.stdout, self._gpu_pattern)
        gpu_count = len(gpu_matches)

        return gpu_count
