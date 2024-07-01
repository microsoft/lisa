from typing import Any, List, Optional

from lisa.sut_orchestrator.util.schema import HostDevicePoolSchema, HostDevicePoolType
from lisa.util import LisaException


class BaseDevicePoolImpl:
    def _create_device_pool(
        self,
        pool_type: HostDevicePoolType,
        vendor_id: str,
        device_id: str,
    ) -> None:
        raise NotImplementedError("'_create_device_pool' is not implemented")

    def _get_primary_nic_id(self) -> List[str]:
        raise NotImplementedError("'_get_primary_nic_id' is not implemented")

    def _get_devices_from_pool(
        self,
        pool_type: HostDevicePoolType,
        count: int,
    ) -> Any:
        raise NotImplementedError("'_get_devices_from_pool' is not implemented")

    def _put_devices_into_pool(
        self,
        node_context: Any,
    ) -> None:
        raise NotImplementedError("'_put_devices_into_pool' is not implemented")

    def _configure_device_passthrough_pool(
        self,
        device_configs: Optional[List[HostDevicePoolSchema]],
        supported_pool_type: List[HostDevicePoolType],
    ) -> None:
        if device_configs:
            pool_types_from_runbook = [config.type for config in device_configs]
            for pool_type in pool_types_from_runbook:
                if pool_type not in supported_pool_type:
                    raise LisaException(
                        f"Pool type '{pool_type}' is not supported by platform"
                    )
            for config in device_configs:
                assert config.vendor_id
                vendor_id = config.vendor_id

                assert config.device_id
                device_id = config.device_id

                self._create_device_pool(
                    pool_type=config.type,
                    vendor_id=vendor_id,
                    device_id=device_id,
                )
