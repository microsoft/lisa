# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Type

from lisa import schema
from lisa.feature import Feature
from lisa.schema import NetworkInterfaceOptionSettings


class NetworkInterface(Feature):
    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return schema.NetworkInterfaceOptionSettings

    @classmethod
    def can_disable(cls) -> bool:
        return False

    def enabled(self) -> bool:
        return True

    def _switch_sriov(self, enable: bool) -> None:
        raise NotImplementedError

    def is_enabled_sriov(self) -> bool:
        raise NotImplementedError


Sriov = NetworkInterfaceOptionSettings(data_path=schema.NetworkDataPath.Sriov)
Synthetic = NetworkInterfaceOptionSettings(data_path=schema.NetworkDataPath.Synthetic)
