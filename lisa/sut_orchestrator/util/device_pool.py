from typing import Any, List, Optional, cast

from lisa.sut_orchestrator.util.schema import (
    AutoDetectIdentifier,
    HostDevicePoolSchema,
    HostDevicePoolType,
    PciAddressIdentifier,
    VendorDeviceIdIdentifier,
)
from lisa.util import LisaException


class BaseDevicePool:
    def __init__(self) -> None:
        self.supported_pool_type: List[Any] = []

    def create_device_pool(
        self,
        pool_type: HostDevicePoolType,
        vendor_id: str,
        device_id: str,
    ) -> None:
        raise NotImplementedError()

    def create_device_pool_from_pci_addresses(
        self,
        pool_type: HostDevicePoolType,
        pci_addr_list: List[str],
    ) -> None:
        raise NotImplementedError()

    def auto_detect_passthrough_nics(
        self,
        count: int = 0,
        require_link_up: bool = False,
        vendor_id: str = "",
        device_id: str = "",
    ) -> List[str]:
        """Auto-detect suitable NICs for device passthrough."""
        raise NotImplementedError()

    def get_primary_nic_id(self) -> List[str]:
        raise NotImplementedError()

    def request_devices(
        self,
        pool_type: HostDevicePoolType,
        count: int,
    ) -> Any:
        raise NotImplementedError()

    def release_devices(
        self,
        node_context: Any,
    ) -> None:
        raise NotImplementedError()

    def configure_device_passthrough_pool(
        self,
        device_configs: Optional[List[HostDevicePoolSchema]],
    ) -> None:
        if device_configs:
            pool_types_from_runbook = [config.type for config in device_configs]
            for pool_type in pool_types_from_runbook:
                if pool_type not in self.supported_pool_type:
                    raise LisaException(
                        f"Pool type '{pool_type}' is not supported by platform"
                    )
            for config in device_configs:
                devices = config.devices
                if isinstance(devices, list) and all(
                    isinstance(d, VendorDeviceIdIdentifier) for d in devices
                ):
                    if len(devices) > 1:
                        raise LisaException(
                            "Device Pool does not support more than one "
                            "vendor/device id list for given pool type"
                        )

                    vendor_device_id = devices[0]
                    assert vendor_device_id.vendor_id.strip()
                    vendor_id = vendor_device_id.vendor_id.strip()

                    assert vendor_device_id.device_id.strip()
                    device_id = vendor_device_id.device_id.strip()

                    self.create_device_pool(
                        pool_type=config.type,
                        vendor_id=vendor_id,
                        device_id=device_id,
                    )
                elif isinstance(devices, (dict, PciAddressIdentifier)):
                    # dataclass_json deserializes Union variants as plain dicts,
                    # so both PciAddressIdentifier and AutoDetectIdentifier arrive
                    # here as dicts. Distinguish by key presence.
                    devices_dict = (
                        devices
                        if isinstance(devices, dict)
                        else {"pci_bdf": devices.pci_bdf}
                    )
                    if "pci_bdf" in devices_dict:
                        bdf_list = devices_dict.get("pci_bdf", [])
                        assert (
                            bdf_list
                        ), "Key 'pci_bdf' is present but the list is empty"
                        pci_addr_list: List[str] = cast(List[str], bdf_list)
                        self.create_device_pool_from_pci_addresses(
                            pool_type=config.type,
                            pci_addr_list=pci_addr_list,
                        )
                    elif "enabled" in devices_dict or "count" in devices_dict:
                        # Treat as AutoDetectIdentifier fields
                        auto_config = AutoDetectIdentifier(
                            enabled=devices_dict.get("enabled", True),
                            count=devices_dict.get("count", 0),  # 0 = detect all
                            vendor_id=devices_dict.get("vendor_id", ""),
                            device_id=devices_dict.get("device_id", ""),
                        )
                        if auto_config.enabled:
                            detected_bdfs = self.auto_detect_passthrough_nics(
                                count=auto_config.count,
                                vendor_id=auto_config.vendor_id,
                                device_id=auto_config.device_id,
                            )
                            self.create_device_pool_from_pci_addresses(
                                pool_type=config.type,
                                pci_addr_list=detected_bdfs,
                            )
                        else:
                            raise LisaException(
                                "Auto-detect is disabled but no devices specified"
                            )
                    else:
                        raise LisaException(
                            f"Unrecognised device dict for pool '{config.type}': "
                            f"{devices_dict}"
                        )
                elif isinstance(devices, AutoDetectIdentifier):
                    # Auto-detect suitable NICs
                    auto_config: AutoDetectIdentifier = devices
                    if auto_config.enabled:
                        detected_bdfs = self.auto_detect_passthrough_nics(
                            count=auto_config.count,
                            vendor_id=auto_config.vendor_id,
                            device_id=auto_config.device_id,
                        )
                        # Create pool from auto-detected BDFs
                        self.create_device_pool_from_pci_addresses(
                            pool_type=config.type,
                            pci_addr_list=detected_bdfs,
                        )
                    else:
                        raise LisaException(
                            "Auto-detect is disabled but no devices specified"
                        )
                else:
                    raise LisaException(
                        f"Unknown device identifier of type: {type(devices)}"
                        f", value: {devices}"
                    )
