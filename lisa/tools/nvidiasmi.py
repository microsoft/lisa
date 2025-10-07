# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from lisa.executable import Tool
from lisa.util import LisaException
from typing import List


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

    def get_gpu_count(self) -> int:
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
    
    def get_gpu_info(self) -> List[tuple]:
        """
        Get GPU information dynamically from nvidia-smi.
        Returns list of tuples (name, device_id_pattern, bridge_count).
        Falls back to hardcoded list if detection fails.
        """
        try:
            # Try to get GPU info dynamically
            result = self.run("--query-gpu=name --format=csv,noheader")
            if result.exit_code != 0 or not result.stdout:
                result = self.run("--query-gpu=name --format=csv,noheader", sudo=True)
            
            if result.exit_code == 0 and result.stdout:
                gpu_names = result.stdout.strip().split('\n')
                dynamic_devices = []
                
                for gpu_name in gpu_names:
                    # Clean up the name (remove extra spaces, model info)
                    gpu_name = gpu_name.strip().split()[0]
                    
                    # Try to find a matching entry in our known list
                    matched = False
                    for known_name, device_id, bridge_count in self.gpu_devices:
                        if known_name.lower() in gpu_name.lower():
                            dynamic_devices.append((gpu_name, device_id, bridge_count))
                            matched = True
                            break
                    
                    if not matched:
                        # New GPU model - add with generic pattern
                        # This ensures new GPUs work even without hardcoded entries
                        dynamic_devices.append((gpu_name, "", 0))
                
                if dynamic_devices:
                    self._log.debug(f"Dynamically detected GPUs: {dynamic_devices}")
                    return dynamic_devices
        except Exception as e:
            self._log.debug(f"Dynamic GPU info detection failed: {e}")
        
        # Fall back to hardcoded list
        self._log.debug("Using hardcoded GPU device list")
        return self.gpu_devices
