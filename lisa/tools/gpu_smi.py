# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import List, Type

from lisa.executable import Tool
from lisa.util import (
    LisaException,
    LisaTimeoutException,
    check_till_timeout,
    find_groups_in_lines,
)


class GpuSmi(Tool):
    """
    Base class for GPU monitoring tools (nvidia-smi, amd-smi, etc.).
    """

    def get_gpu_count(self) -> int:
        """Get the number of GPUs detected by the SMI tool"""
        raise NotImplementedError


class NvidiaSmi(GpuSmi):
    # tuple of gpu device names and their device id pattern
    # e.g. Tesla GPU device has device id "47505500-0001-0000-3130-444531303244"
    # A10-4Q device id "56475055-0002-0000-3130-444532323336"
    gpu_devices = (
        ("Tesla", "47505500", 0),
        ("A100", "44450000", 6),
        ("H100", "44453233", 0),
        ("A10-4Q", "56475055", 0),
        ("A10-8Q", "3e810200", 0),
    )

    @property
    def command(self) -> str:
        return "nvidia-smi"

    @property
    def can_install(self) -> bool:
        return False

    def get_gpu_count(self) -> int:
        # After driver installation and reboot, NVML may not be ready
        # immediately. Exit code 9 means "NVML uninitialized" — a transient
        # condition that resolves once the GPU finishes initialising.
        # Retry with delays to accommodate large GPU SKUs (e.g. H100).
        last_result = None

        def _try_nvidia_smi() -> bool:
            nonlocal last_result
            result = self.run("-L", force_run=True)
            if result.exit_code != 0 or (result.exit_code == 0 and result.stdout == ""):
                result = self.run("-L", sudo=True, force_run=True)
            last_result = result
            if result.exit_code == 0 and result.stdout != "":
                return True
            # Only retry on exit code 9 (NVML uninitialized); fail fast
            # for non-transient errors (e.g. command not found, driver missing).
            if result.exit_code not in (0, 9):
                raise LisaException(
                    f"nvidia-smi -L failed with non-transient exit_code "
                    f"{result.exit_code}. stderr: '{result.stderr}'. "
                    f"stdout: '{result.stdout}'"
                )
            self._log.debug(
                f"nvidia-smi returned exit_code {result.exit_code}, "
                f"waiting for NVML initialization..."
            )
            return False

        try:
            check_till_timeout(
                _try_nvidia_smi,
                timeout_message=(
                    "nvidia-smi -L timed out waiting for NVML initialization. "
                    "Verify the NVIDIA driver is installed and NVML is initialized."
                ),
                timeout=300,  # 10 attempts * 30s interval = 5 minutes max wait
                interval=30,
            )
        except LisaTimeoutException:
            if last_result is not None:
                raise LisaException(
                    "nvidia-smi -L failed after retries. "
                    f"exit_code={last_result.exit_code}, "
                    f"stderr='{last_result.stderr}', "
                    f"stdout='{last_result.stdout}'. "
                    "Verify the NVIDIA driver is installed "
                    "and NVML is initialized."
                ) from None
            raise

        if last_result is None:
            raise LisaException("nvidia-smi -L was not executed")
        gpu_types = [x[0] for x in self.gpu_devices]
        device_count = 0
        for gpu_type in gpu_types:
            device_count += last_result.stdout.count(gpu_type)

        return device_count


class AmdSmi(GpuSmi):
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
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        # Lazy import to avoid circular dependency
        from lisa.tools.gpu_drivers import AmdGpuDriver

        return [AmdGpuDriver]

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
                    f"Failed to query AMD GPUs using 'amd-smi list'. "
                    f"Exit code: {result.exit_code}, "
                    f"stderr: '{result.stderr}'. "
                    f"stdout: '{result.stdout}', "
                    f"Ensure AMD GPU driver is installed and amdgpu module is loaded."
                )

        gpu_matches = find_groups_in_lines(result.stdout, self._gpu_pattern)
        gpu_count = len(gpu_matches)

        return gpu_count
