from collections.abc import Mapping
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
        raise LisaException(
            f"Location-path identifiers are not supported by "
            f"{type(self).__name__} for pool type '{pool_type}'."
        )

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
        if not isinstance(devices, list):
            return False

        return all(isinstance(device, VendorDeviceIdIdentifier) for device in devices)

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
            self._configure_dict_identifier_pool(config, cast(Dict[str, Any], devices))
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
        has_pci_bdf = "pci_bdf" in devices
        has_location_path = "location_path" in devices

        if has_pci_bdf and has_location_path:
            raise LisaException(
                "Device configuration must specify exactly one of "
                "'pci_bdf' or 'location_path'"
            )

        if has_pci_bdf:
            self.create_device_pool_from_pci_addresses(
                pool_type=config.type,
                pci_addr_list=self._normalize_pci_address_list(devices["pci_bdf"]),
            )
            return

        if has_location_path:
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
        return self._normalize_string_list(
            raw_value=pci_addr_value,
            field_name="PCI address list 'pci_bdf'",
        )

    def _normalize_location_path_list(self, location_path_value: Any) -> List[str]:
        return self._normalize_string_list(
            raw_value=location_path_value,
            field_name="Location path list 'location_path'",
        )

    def _normalize_string_list(self, raw_value: Any, field_name: str) -> List[str]:
        if raw_value is None:
            raise LisaException(f"{field_name} must not be null")

        if isinstance(raw_value, str):
            raw_values = [raw_value]
        elif isinstance(raw_value, Mapping):
            raise LisaException(
                f"{field_name} must be a string or an iterable of strings, "
                "not a mapping"
            )
        else:
            try:
                raw_values = list(raw_value)
            except TypeError as identifier_error:
                raise LisaException(
                    f"{field_name} must be a string or an iterable of strings"
                ) from identifier_error

        normalized_values: List[str] = []
        for raw_item in raw_values:
            if not isinstance(raw_item, str):
                raise LisaException(
                    f"{field_name} must contain only strings; got "
                    f"{type(raw_item).__name__}"
                )

            normalized_item = raw_item.strip()
            if normalized_item:
                normalized_values.append(normalized_item)

        if not normalized_values:
            raise LisaException(f"{field_name} must not be empty")

        return normalized_values
