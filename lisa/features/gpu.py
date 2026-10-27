# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass
from functools import partial
from typing import Any, List, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.feature import Feature
from lisa.tools import Cat, Find, Lspci, Lsvmbus, NvidiaSmi, Readlink
from lisa.tools.gpu_drivers import ComputeSDK
from lisa.tools.lspci import CONTROLLER_ID_DICT, VENDOR_ID_MICROSOFT, PciDevice
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

    def _choose_value(self, capability: Any) -> Any:
        return self


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
        cat = self._node.tools[Cat]
        find = self._node.tools[Find]
        readlink = self._node.tools[Readlink]
        gpu_classes = tuple(
            f"0x{class_id}"
            for class_id in CONTROLLER_ID_DICT[constants.DEVICE_TYPE_GPU]
        )
        device_list = self._node.tools[Lsvmbus].get_device_channels(force_run=True)
        for device in device_list:
            if device.class_id.lower() != "44c4f61d-4444-4400-9d52-802e27ede19f":
                continue
            # Instance IDs are not GPU model identifiers. Inspect PCI endpoints
            # beneath each VMBus channel so bridges are not counted as GPUs.
            device_path = readlink.get_canonical_path(
                f"/sys/bus/vmbus/devices/{device.device_id}"
            )
            class_files = find.find_files(
                self._node.get_pure_path(device_path),
                name_pattern="class",
                path_pattern="*/pci*/*/class",
                file_type="f",
            )
            for class_file in class_files:
                pci_class = cat.read(class_file, force_run=True).strip().lower()
                if not pci_class.startswith(gpu_classes):
                    continue
                pci_path = self._node.get_pure_path(class_file).parent
                vendor = (
                    cat.read(str(pci_path / "vendor"), force_run=True).strip().lower()
                )
                if vendor == f"0x{VENDOR_ID_MICROSOFT}":
                    continue
                lsvmbus_device_count += 1
                self._log.debug(
                    f"GPU PCI device {pci_path} found on VMBus {device.device_id}"
                )

        return lsvmbus_device_count

    def get_gpu_count_with_lspci(self) -> int:
        return len(self._get_gpu_from_lspci())

    def get_gpu_count_with_vendor_cmd(self) -> int:
        nvidiasmi = self._node.tools[NvidiaSmi]
        return nvidiasmi.get_gpu_count()

    def get_supported_driver(self) -> ComputeSDK:
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
