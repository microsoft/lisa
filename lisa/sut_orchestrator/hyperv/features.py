from typing import Type, Any, List
from lisa import schema
from lisa.feature import Feature
from lisa.tools import IpInfo, HyperV


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
        raise NotImplementedError("SR-IOV is not supported on Hyper-V platform.")

    def is_enabled_sriov(self) -> bool:
        return False

    def create_route_table(
        self,
        nic_name: str,
        route_name: str,
        subnet_mask: str,
        dest_hop: str,
        em_first_hop: str = "",
        next_hop_type: str = "",
    ) -> None:
        raise NotImplementedError(
            "Route table creation is not supported on Hyper-V platform."
        )

    def switch_ip_forwarding(self, enable: bool, private_ip_addr: str = "") -> None:
        raise NotImplementedError("IP forwarding is not supported on Hyper-V platform.")

    def attach_nics(
        self, extra_nic_count: int, enable_accelerated_networking: bool = True
    ) -> None:
        hyperv: HyperV = self._node.tools[HyperV]
        for i in range(extra_nic_count):
            nic_name = f"{self._node.name}-extra-{i}"
            hyperv.add_network_adapter(self._node.name, nic_name)

    def remove_extra_nics(self) -> None:
        hyperv: HyperV = self._node.tools[HyperV]
        hyperv.remove_extra_network_adapters(self._node.name)

    def reload_module(self) -> None:
        raise NotImplementedError("Module reload is not supported on Hyper-V platform.")

    def get_nic_count(self, is_sriov_enabled: bool = True) -> int:
        hyperv = self._node.tools[HyperV]
        return hyperv.get_network_adapter_count(self._node.name)

    def get_all_primary_nics_ip_info(self) -> List[IpInfo]:
        hyperv = self._node.tools[HyperV]
        return hyperv.get_all_primary_nics_ip_info(self._node.name)

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self.origin_extra_synthetic_nics_count = 0
        self.origin_extra_sriov_nics_count = 0
