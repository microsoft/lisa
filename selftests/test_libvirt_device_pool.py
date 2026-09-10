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
    def test_stabilize_management_route_away_from_passthrough_nic(self) -> None:
        device_pool_module = _load_device_pool_module()
        host_node = MagicMock()

        def execute(command: str = "", **kwargs: object) -> MagicMock:
            command = str(kwargs.get("cmd", command))
            result = MagicMock(exit_code=0, stdout="", stderr="")
            if command == 'printf "%s" "$SSH_CONNECTION"':
                result.stdout = "192.0.2.10 50123 198.51.100.214 22"
            elif command == "ip -o -4 addr show":
                result.stdout = (
                    "2: eth0    inet 198.51.100.16/24 scope global eth0\n"
                    "3: eth1    inet 198.51.100.214/24 scope global eth1"
                )
            elif command.endswith("oif eth1"):
                result.stdout = (
                    "192.0.2.10 via 198.51.100.1 dev eth1 "
                    + "src 198.51.100.214 uid 1000"
                )
            elif command.startswith("ip -o -4 route get"):
                result.stdout = (
                    "192.0.2.10 via 198.51.100.1 dev eth0 "
                    + "src 198.51.100.214 uid 1000"
                )
            return result

        host_node.execute.side_effect = execute
        pool = device_pool_module.LibvirtDevicePool(host_node, MagicMock())
        pool.available_host_devices = {
            device_pool_module.HostDevicePoolType.PCI_NIC: {
                "iommu_grp_31": [
                    device_pool_module.DeviceAddressSchema(
                        domain="0000", bus="19", slot="00", function="0"
                    )
                ]
            }
        }
        host_node.tools[
            device_pool_module.Readlink
        ].get_canonical_path.return_value = "/sys/devices/pci0000:00/0000:19:00.0"

        pool._stabilize_management_route()

        commands = [call.kwargs["cmd"] for call in host_node.execute.call_args_list]
        self.assertIn(
            "ip route add 192.0.2.10/32 via 198.51.100.1 dev eth1 "
            "src 198.51.100.214 proto static",
            commands,
        )
        self.assertEqual(
            "ip route del 192.0.2.10/32 via 198.51.100.1 dev eth1 "
            "src 198.51.100.214 proto static",
            pool._management_route_cleanup_command,
        )

        pool.cleanup()

        commands = [call.kwargs["cmd"] for call in host_node.execute.call_args_list]
        self.assertIn(
            "ip route del 192.0.2.10/32 via 198.51.100.1 dev eth1 "
            "src 198.51.100.214 proto static",
            commands,
        )
        self.assertEqual("", pool._management_route_cleanup_command)

    def test_management_route_guard_skips_management_interface(self) -> None:
        device_pool_module = _load_device_pool_module()
        host_node = MagicMock()

        def execute(command: str = "", **kwargs: object) -> MagicMock:
            command = str(kwargs.get("cmd", command))
            result = MagicMock(exit_code=0, stdout="", stderr="")
            if command == 'printf "%s" "$SSH_CONNECTION"':
                result.stdout = "192.0.2.10 50123 198.51.100.214 22"
            elif command == "ip -o -4 addr show":
                result.stdout = "3: eth1    inet 198.51.100.214/24 scope global eth1"
            elif command.startswith("ip -o -4 route get"):
                result.stdout = (
                    "192.0.2.10 via 198.51.100.1 dev eth1 "
                    "src 198.51.100.214 uid 1000"
                )
            return result

        host_node.execute.side_effect = execute
        pool = device_pool_module.LibvirtDevicePool(host_node, MagicMock())

        pool._stabilize_management_route()

        commands = [call.kwargs["cmd"] for call in host_node.execute.call_args_list]
        self.assertFalse(any("route add" in command for command in commands))
        self.assertEqual("", pool._management_route_cleanup_command)
        host_node.tools[
            device_pool_module.Readlink
        ].get_canonical_path.assert_not_called()

    def test_management_route_cleanup_tolerates_disconnected_host(self) -> None:
        device_pool_module = _load_device_pool_module()
        host_node = MagicMock()
        host_node.execute.side_effect = SSHException("SSH session not active")
        pool = device_pool_module.LibvirtDevicePool(host_node, MagicMock())
        pool._management_route_cleanup_command = "ip route del 192.0.2.10/32"

        pool.cleanup()

        self.assertEqual(
            "ip route del 192.0.2.10/32", pool._management_route_cleanup_command
        )
        host_node.log.debug.assert_called_once()

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
