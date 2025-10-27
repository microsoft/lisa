# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass
from enum import Enum
from functools import partial
from typing import Any, List, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.feature import Feature
from lisa.tools import Lspci, Lsvmbus, NvidiaSmi
from lisa.tools.lspci import PciDevice
from lisa.util import constants

FEATURE_NAME_GPU = "Gpu"


@dataclass_json()
@dataclass()
class GpuSettings(schema.FeatureSettings):
    type: str = FEATURE_NAME_GPU
    is_enabled: bool = False

    def __hash__(self) -> int:
        return hash(self._get_key())

    def _get_key(self) -> str:
        return f"{self.type}/{self.is_enabled}"

    def _generate_min_capability(self, capability: Any) -> Any:
        return self


class ComputeSDK(str, Enum):
    GRID = "GRID"
    CUDA = "CUDA"
    AMD = "AMD"


class Gpu(Feature):
    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return GpuSettings

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_GPU

    @classmethod
    def can_disable(cls) -> bool:
        return True

    @classmethod
    def remove_virtual_gpus(cls, devices: List[PciDevice]) -> List[PciDevice]:
        return [x for x in devices if x.vendor != "Microsoft Corporation"]

    def enabled(self) -> bool:
        return True

    def is_supported(self) -> bool:
        raise NotImplementedError

    def is_module_loaded(self) -> bool:
        lspci_tool = self._node.tools[Lspci]
        pci_devices = self._get_gpu_from_lspci()
        for device in pci_devices:
            used_module = lspci_tool.get_used_module(device.slot)
            if used_module:
                return True
        return False

    def get_gpu_count_with_lsvmbus(self) -> int:
        lsvmbus_device_count = 0
        bridge_device_count = 0

        lsvmbus_tool = self._node.tools[Lsvmbus]
        device_list = lsvmbus_tool.get_device_channels()
        for device in device_list:
            for name, id_, bridge_count in NvidiaSmi.gpu_devices:
                if id_ in device.device_id:
                    lsvmbus_device_count += 1
                    bridge_device_count = bridge_count
                    self._log.debug(f"GPU device {name} found!")
                    break

        return lsvmbus_device_count - bridge_device_count

    def get_gpu_count_with_lspci(self) -> int:
        return len(self._get_gpu_from_lspci())

    def get_gpu_count_with_vendor_cmd(self) -> int:
        nvidiasmi = self._node.tools[NvidiaSmi]
        return nvidiasmi.get_gpu_count()

    def get_supported_driver(self) -> List[ComputeSDK]:
        raise NotImplementedError()

    def _install_driver_using_platform_feature(self) -> None:
        raise NotImplementedError()

    def _get_gpu_from_lspci(self) -> List[PciDevice]:
        lspci_tool = self._node.tools[Lspci]
        device_list = lspci_tool.get_devices_by_type(
            constants.DEVICE_TYPE_GPU, force_run=True
        )
        # Remove Microsoft Virtual one. It presents with GRID driver.
        return self.remove_virtual_gpus(device_list)


GpuEnabled = partial(GpuSettings, is_enabled=True)
