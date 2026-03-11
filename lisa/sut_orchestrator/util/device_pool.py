from typing import Any, Dict, List, Optional, cast

from lisa.sut_orchestrator.util.schema import (
    DeviceLocationPathIdentifier,
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

    def resolve_requested_pci_address(
        self,
        pool_type: HostDevicePoolType,
        requested_bdf: str,
    ) -> str:
        return requested_bdf

    def create_device_pool_from_location_paths(
        self,
        pool_type: HostDevicePoolType,
        location_paths: List[str],
    ) -> None:
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
        if not device_configs:
            return

        self._validate_supported_pool_types(device_configs)
        for config in device_configs:
            self._configure_passthrough_pool(config)

    def _validate_supported_pool_types(
        self,
        device_configs: List[HostDevicePoolSchema],
    ) -> None:
        for config in device_configs:
            if config.type not in self.supported_pool_type:
                raise LisaException(
                    f"Pool type '{config.type}' is not supported by platform"
                )

    def _configure_passthrough_pool(self, config: HostDevicePoolSchema) -> None:
        devices = config.devices
        if self._is_vendor_device_id_list(devices):
            vendor_device_list = cast(List[VendorDeviceIdIdentifier], devices)
            self._configure_vendor_device_id_pool(config, vendor_device_list)
            return

        if isinstance(
            devices,
            (dict, PciAddressIdentifier, DeviceLocationPathIdentifier),
        ):
            self._configure_identifier_pool(config, devices)
            return

        raise LisaException(
            f"Unknown device identifier of type: {type(devices)}" f", value: {devices}"
        )

    def _is_vendor_device_id_list(self, devices: Any) -> bool:
        return isinstance(devices, list) and all(
            isinstance(device, VendorDeviceIdIdentifier) for device in devices
        )

    def _configure_vendor_device_id_pool(
        self,
        config: HostDevicePoolSchema,
        devices: List[VendorDeviceIdIdentifier],
    ) -> None:
        if not devices:
            raise LisaException(
                "Device pool configuration has no vendor/device "
                "id entries for pool type"
            )
        if len(devices) > 1:
            raise LisaException(
                "Device Pool does not support more than one "
                "vendor/device id list for given pool type"
            )

        vendor_device_id = devices[0]
        vendor_id = vendor_device_id.vendor_id.strip()
        if not vendor_id:
            raise LisaException("Device pool configuration has empty 'vendor_id'")

        device_id = vendor_device_id.device_id.strip()
        if not device_id:
            raise LisaException("Device pool configuration has empty 'device_id'")

        self.create_device_pool(
            pool_type=config.type,
            vendor_id=vendor_id,
            device_id=device_id,
        )

    def _configure_identifier_pool(
        self,
        config: HostDevicePoolSchema,
        devices: Any,
    ) -> None:
        if isinstance(devices, dict):
            self._configure_dict_identifier_pool(config, devices)
        elif isinstance(devices, PciAddressIdentifier):
            self.create_device_pool_from_pci_addresses(
                pool_type=config.type,
                pci_addr_list=self._normalize_pci_address_list(devices.pci_bdf),
            )
        else:
            self.create_device_pool_from_location_paths(
                pool_type=config.type,
                location_paths=self._normalize_location_path_list(
                    devices.location_path
                ),
            )

    def _configure_dict_identifier_pool(
        self,
        config: HostDevicePoolSchema,
        devices: Dict[str, Any],
    ) -> None:
        if "pci_bdf" in devices:
            self.create_device_pool_from_pci_addresses(
                pool_type=config.type,
                pci_addr_list=self._normalize_pci_address_list(devices["pci_bdf"]),
            )
            return

        if "location_path" in devices:
            self.create_device_pool_from_location_paths(
                pool_type=config.type,
                location_paths=self._normalize_location_path_list(
                    devices["location_path"]
                ),
            )
            return

        raise LisaException(
            "Key not found in device configuration: expected "
            "'pci_bdf' or 'location_path'"
        )

    def _normalize_pci_address_list(self, pci_addr_value: Any) -> List[str]:
        if isinstance(pci_addr_value, str):
            pci_addr_list = [pci_addr_value]
        else:
            pci_addr_list = list(pci_addr_value)

        normalized_addresses = [addr.strip() for addr in pci_addr_list if addr.strip()]
        if not normalized_addresses:
            raise LisaException("PCI address list 'pci_bdf' must not be empty")

        return normalized_addresses

    def _normalize_location_path_list(self, location_path_value: Any) -> List[str]:
        if isinstance(location_path_value, str):
            location_paths = [location_path_value]
        else:
            location_paths = list(location_path_value)

        normalized_paths = [path.strip() for path in location_paths if path.strip()]
        if not normalized_paths:
            raise LisaException("Location path list 'location_path' must not be empty")

        return normalized_paths
