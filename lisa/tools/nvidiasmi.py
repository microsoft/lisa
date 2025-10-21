# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from lisa.executable import Tool
from lisa.util import LisaException


class NvidiaSmi(Tool):
    # tuple of gpu device names and their device id pattern
    # e.g. Tesla GPU device has device id "47505500-0001-0000-3130-444531303244"
    # A10-4Q device id "56475055-0002-0000-3130-444532323336"
    gpu_devices = (
        ("Tesla", "47505500", 0),
        ("A100", "44450000", 6),
        ("H100", "44453233", 0),
        ("A10-4Q", "56475055", 0),
        ("A10-8Q", "3e810200", 0),
        ("GB200", "42333130", 0),
    )

    @property
    def command(self) -> str:
        return "nvidia-smi"

    @property
    def can_install(self) -> bool:
        return False

    def get_gpu_count(self, known_only: bool = True) -> int:
        """
        Get GPU count from nvidia-smi output.

        Args:
            known_only: If True, only count GPUs in the hardcoded list.
                       If False, count all GPUs reported by nvidia-smi.

        Returns:
            Number of GPUs detected.
        """
        result = self.run("-L")
        if result.exit_code != 0 or (result.exit_code == 0 and result.stdout == ""):
            result = self.run("-L", sudo=True)
            if result.exit_code != 0 or (result.exit_code == 0 and result.stdout == ""):
                raise LisaException(
                    f"nvidia-smi command exited with exit_code {result.exit_code}"
                )

        if known_only:
            # Original behavior: only count GPUs in the hardcoded list
            gpu_types = [x[0] for x in self.gpu_devices]
            device_count = 0
            for gpu_type in gpu_types:
                device_count += result.stdout.count(gpu_type)

            if device_count > 0:
                self._log.debug(f"nvidia-smi detected {device_count} known GPU(s)")

            return device_count
        else:
            # New behavior: count all GPUs regardless of model
            gpu_lines = [
                line
                for line in result.stdout.splitlines()
                if line.strip().startswith("GPU ")
            ]
            gpu_count = len(gpu_lines)

            self._log.debug(f"nvidia-smi detected {gpu_count} GPU(s)")
            for line in gpu_lines:
                self._log.debug(f"  {line}")

            return gpu_count
