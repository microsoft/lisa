# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from types import SimpleNamespace
from typing import Any, cast
from unittest import TestCase

from lisa.sut_orchestrator.libvirt.libvirt_device_pool import LibvirtDevicePool
from lisa.sut_orchestrator.libvirt.schema import DeviceAddressSchema
from lisa.sut_orchestrator.util.schema import HostDevicePoolType


class LibvirtDevicePoolTestCase(TestCase):
    def _create_pool(self) -> LibvirtDevicePool:
        return LibvirtDevicePool(cast(Any, SimpleNamespace()), cast(Any, None))

    def test_request_device_from_many_iommu_groups(self) -> None:
        device_pool = self._create_pool()
        pool_type = HostDevicePoolType.PCI_NIC
        devices_by_group = {
            f"iommu_grp_{index}": [
                DeviceAddressSchema(
                    domain="0000",
                    bus=f"{index:02x}",
                    slot="00",
                    function="0",
                )
            ]
            for index in range(32)
        }
        device_pool.available_host_devices[pool_type] = devices_by_group

        devices = device_pool.request_devices(pool_type, 1)

        self.assertEqual(["00"], [device.bus for device in devices])
        self.assertNotIn(
            "iommu_grp_0",
            device_pool.available_host_devices[pool_type],
        )
        self.assertEqual(
            31,
            len(device_pool.available_host_devices[pool_type]),
        )

    def test_request_devices_prefers_exact_group_combination(self) -> None:
        device_pool = self._create_pool()
        pool_type = HostDevicePoolType.PCI_NIC
        device_pool.available_host_devices[pool_type] = {
            "oversized": [DeviceAddressSchema() for _ in range(3)],
            "first": [DeviceAddressSchema(bus="01")],
            "second": [DeviceAddressSchema(bus="02")],
        }

        devices = device_pool.request_devices(pool_type, 2)

        self.assertEqual(["01", "02"], [device.bus for device in devices])
        self.assertIn(
            "oversized",
            device_pool.available_host_devices[pool_type],
        )

    def test_request_devices_uses_smallest_group_count_as_fallback(self) -> None:
        device_pool = self._create_pool()
        pool_type = HostDevicePoolType.PCI_NIC
        device_pool.available_host_devices[pool_type] = {
            "oversized": [DeviceAddressSchema() for _ in range(3)],
            "first": [DeviceAddressSchema()],
        }

        devices = device_pool.request_devices(pool_type, 2)

        self.assertEqual(3, len(devices))
        self.assertNotIn(
            "oversized",
            device_pool.available_host_devices[pool_type],
        )
