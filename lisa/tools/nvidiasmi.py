# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import List, Tuple
from lisa.executable import Tool
from lisa.util import LisaException


class NvidiaSmi(Tool):
    # tuple of gpu device names and their device id pattern
    # e.g. Tesla GPU device has device id "47505500-0001-0000-3130-444531303244"
    # A10-4Q device id "56475055-0002-0000-3130-444532323336"
    # Legacy static list - kept for backward compatibility
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

    def get_gpu_count_old(self) -> int:
        result = self.run("-L")
        if result.exit_code != 0 or (result.exit_code == 0 and result.stdout == ""):
            result = self.run("-L", sudo=True)
            if result.exit_code != 0 or (result.exit_code == 0 and result.stdout == ""):
                raise LisaException(
                    f"nvidia-smi command exited with exit_code {result.exit_code}"
                )
        gpu_types = [x[0] for x in self.gpu_devices]
        device_count = 0
        for gpu_type in gpu_types:
            device_count += result.stdout.count(gpu_type)

        return device_count
    
    def get_gpu_count(self) -> int:
        result = self.run("-L")
        if result.exit_code != 0 or (result.exit_code == 0 and result.stdout == ""):
            result = self.run("-L", sudo=True)
            if result.exit_code != 0 or (result.exit_code == 0 and result.stdout == ""):
                raise LisaException(
                    f"nvidia-smi command exited with exit_code {result.exit_code}"
                )
        
        # Count GPUs by counting lines that start with "GPU"
        # nvidia-smi -L output format: "GPU 0: Tesla T4 (UUID: GPU-xxxxx)"
        gpu_count = len([line for line in result.stdout.splitlines() 
                        if line.strip().startswith("GPU")])
        
        return gpu_count
    
    def get_gpu_device_info(self) -> List[Tuple[str, str]]:
        """
        Dynamically get GPU device names and UUIDs from nvidia-smi
        Returns list of tuples (gpu_name, uuid)
        """
        result = self.run("-L")
        if result.exit_code != 0 or (result.exit_code == 0 and result.stdout == ""):
            result = self.run("-L", sudo=True)
            if result.exit_code != 0:
                raise LisaException(
                    f"nvidia-smi command exited with exit_code {result.exit_code}"
                )
        
        gpu_info = []
        # Parse output like: "GPU 0: Tesla T4 (UUID: GPU-xxxxx)"
        pattern = r"GPU \d+: ([^(]+) \(UUID: ([^)]+)\)"
        
        for line in result.stdout.splitlines():
            match = re.search(pattern, line)
            if match:
                gpu_name = match.group(1).strip()
                uuid = match.group(2).strip()
                gpu_info.append((gpu_name, uuid))
        
        return gpu_info
