# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from functools import partial
from typing import Any, List, Type

from lisa import schema
from lisa.feature import Feature
from lisa.schema import NetworkInterfaceOptionSettings
from lisa.tools import IpInfo


class NetworkInterface(Feature):
    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return schema.NetworkInterfaceOptionSettings

    @classmethod
    def can_disable(cls) -> bool:
        return False

    def enabled(self) -> bool:
        return True

    def switch_sriov(
        self, enable: bool, wait: bool = True, reset_connections: bool = True
    ) -> None:
        raise NotImplementedError

    def is_enabled_sriov(self) -> bool:
        raise NotImplementedError

    def create_route_table(
        self,
        nic_name: str,
        route_name: str,
        subnet_mask: str,
        dest_hop: str,
        em_first_hop: str = "",
        next_hop_type: str = "",
    ) -> None:
        raise NotImplementedError

    def switch_ip_forwarding(self, enable: bool, private_ip_addr: str = "") -> None:
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

    def get_nic_cap_count(self) -> int:
        raise NotImplementedError

    def get_all_primary_nics_ip_info(self) -> List[IpInfo]:
        raise NotImplementedError

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self.origin_extra_synthetic_nics_count: int = 0
        self.origin_extra_sriov_nics_count: int = 0


Sriov = partial(NetworkInterfaceOptionSettings, data_path=schema.NetworkDataPath.Sriov)
Synthetic = partial(
    NetworkInterfaceOptionSettings, data_path=schema.NetworkDataPath.Synthetic
)
