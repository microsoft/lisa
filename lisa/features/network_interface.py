# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from functools import partial
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

    def switch_sriov(self, enable: bool, wait: bool = True) -> None:
        raise NotImplementedError

    def is_enabled_sriov(self) -> bool:
        raise NotImplementedError

    def attach_nics(
        self, extra_nic_count: int, enable_accelerated_networking: bool = True
    ) -> None:
        raise NotImplementedError

    def remove_extra_nics(self) -> None:
        raise NotImplementedError

    def reload_module(self) -> None:
        raise NotImplementedError

    def get_nic_count(self, is_sriov_enabled: bool = True) -> int:
        raise NotImplementedError


Sriov = partial(NetworkInterfaceOptionSettings, data_path=schema.NetworkDataPath.Sriov)
Synthetic = partial(
    NetworkInterfaceOptionSettings, data_path=schema.NetworkDataPath.Synthetic
)
