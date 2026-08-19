# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import importlib
import sys
from types import ModuleType
from unittest import TestCase
from unittest.mock import MagicMock

from paramiko.ssh_exception import SSHException


def _load_device_pool_module() -> ModuleType:
    for module_name in ("libvirt", "libvirtaio"):
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError as identifier:
            if identifier.name != module_name:
                raise
            module = ModuleType(module_name)
            if module_name == "libvirt":
                module.__dict__.update(
                    {
                        "virDomain": type("virDomain", (), {}),
                        "virStream": type("virStream", (), {}),
                    }
                )
            sys.modules[module_name] = module

    return importlib.import_module("lisa.sut_orchestrator.libvirt.libvirt_device_pool")


class LibvirtDevicePoolTestCase(TestCase):
    def test_release_devices_without_host_connection(self) -> None:
        device_pool_module = _load_device_pool_module()
        host_node = MagicMock()
        host_node.execute.side_effect = SSHException("SSH session not active")
        pool = device_pool_module.LibvirtDevicePool(host_node, MagicMock())
        pool_type = device_pool_module.HostDevicePoolType.PCI_NIC
        device = device_pool_module.DeviceAddressSchema(
            domain="0000", bus="3b", slot="00", function="0"
        )
        pool.available_host_devices = {
            pool_type: {"iommu_grp_12": [device]},
        }

        allocated_devices = pool.request_devices(pool_type, 1)
        node_context = device_pool_module.NodeContext(
            passthrough_devices=[
                device_pool_module.DevicePassthroughContext(
                    pool_type=pool_type,
                    device_list=allocated_devices,
                )
            ]
        )

        pool.release_devices(node_context)

        self.assertEqual(
            {"iommu_grp_12": [device]}, pool.available_host_devices[pool_type]
        )
        self.assertEqual([], node_context.passthrough_devices)
        self.assertEqual({}, pool._allocated_device_groups)
        host_node.execute.assert_not_called()
