# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from contextlib import contextmanager
from functools import partial
from typing import Any, Iterator, List, Type

from lisa import schema
from lisa.feature import Feature
from lisa.schema import NetworkInterfaceOptionSettings
from lisa.tools import IpInfo
from lisa.util import LisaException, SkippedException


class NetworkInterface(Feature):
    runtime_synthetic = False

    def verify_synthetic_path(self) -> None:
        expected = {nic.mac_addr for nic in self.get_all_primary_nics_ip_info()}
        self._node.nics.reload()
        synthetic = {
            nic.mac_addr
            for nic in self._node.nics.nics.values()
            if not (nic.is_infiniband or nic.is_pci_only_nic or nic.lower)
        }
        if not expected or expected - synthetic or self.get_nic_count():
            raise LisaException(
                f"Synthetic path not active on every NIC: expected {expected}, "
                f"guest synthetic MACs {synthetic}"
            )
        # A fresh SSH round trip also checks connectivity with the VFs absent.
        self._node.execute("echo connected", timeout=30, expected_exit_code=0)

    @contextmanager
    def synthetic_path(self) -> Iterator[None]:
        self._node.nics.reload()
        for nic in self._node.nics.nics.values():
            if not nic.is_infiniband and nic.is_pci_only_nic:
                raise SkippedException(
                    f"No synthetic pairing for Ethernet NIC {nic.name}"
                )
        if not self.is_enabled_sriov():
            raise LisaException("Expected every NIC to have AN enabled before the test")
        original_count = self.get_nic_count()
        self._log.info("Testing post-deployment synthetic networking; disabling AN")
        try:
            self.switch_sriov(False)
            self.verify_synthetic_path()
            self.runtime_synthetic = True
            yield
        finally:
            self.runtime_synthetic = False
            restored = False
            try:
                self.switch_sriov(True)
                if (
                    self.get_nic_count() != original_count
                    or not self.is_enabled_sriov()
                ):
                    raise LisaException(
                        "Original accelerated NIC configuration not restored"
                    )
                restored = True
            finally:
                if not restored:
                    self._node.mark_dirty()

    def attach_synthetic_nics(self, extra_nic_count: int) -> None:
        self.attach_nics(
            extra_nic_count, enable_accelerated_networking=self.runtime_synthetic
        )
        if self.runtime_synthetic:
            self.switch_sriov(False)
            self.verify_synthetic_path()

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

    def get_all_primary_nics_ip_info(self) -> List[IpInfo]:
        raise NotImplementedError

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self.origin_extra_synthetic_nics_count: int = 0
        self.origin_extra_sriov_nics_count: int = 0


Sriov = partial(NetworkInterfaceOptionSettings, data_path=schema.NetworkDataPath.Sriov)
Synthetic = partial(
    NetworkInterfaceOptionSettings, data_path=schema.NetworkDataPath.Synthetic
)
