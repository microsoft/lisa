# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from lisa.executable import Tool
from lisa.util import LisaException


class NvidiaSmi(Tool):
    # tuple of gpu device names and their device id pattern
    # e.g. Tesla GPU device has device id "47505500-0001-0000-3130-444531303244"
    gpu_devices = (
        ("Tesla", "47505500", 0),
        ("A100", "44450000", 6),
        ("H100", "44453233", 0),
    )

    @property
    def command(self) -> str:
        return "nvidia-smi"

    @property
    def can_install(self) -> bool:
        return False

    def get_gpu_count(self) -> int:
        result = self.run("-L")
        if result.exit_code != 0 or (result.exit_code == 0 and result.stdout == ""):
            raise LisaException(
                f"nvidia-smi command exited with exit_code {result.exit_code}"
            )
        gpu_types = [x[0] for x in self.gpu_devices]
        device_count = 0
        for gpu_type in gpu_types:
            device_count += result.stdout.count(gpu_type)

        return device_count
