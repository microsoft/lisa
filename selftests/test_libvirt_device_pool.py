# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import importlib
import sys
from dataclasses import dataclass, field
from types import ModuleType
from typing import TYPE_CHECKING, List, Tuple
from unittest import TestCase
from unittest.mock import MagicMock, patch

from assertpy import assert_that
from paramiko.ssh_exception import SSHException

if TYPE_CHECKING:
    from lisa.sut_orchestrator.libvirt.libvirt_device_pool import LibvirtDevicePool


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


@dataclass
class _ManagementRouteState:
    routes: List[str] = field(default_factory=list)
    peer_ip: str = "192.0.2.10"
    lose_add_ack: bool = False
    fail_add: bool = False
    force_passthrough_route: bool = False


class LibvirtDevicePoolTestCase(TestCase):
    def test_pool_configuration_does_not_change_management_route(self) -> None:
        device_pool_module = _load_device_pool_module()
        host_node = MagicMock()
        host_node.execute.return_value = MagicMock(stdout="")
        pool = device_pool_module.LibvirtDevicePool(host_node, MagicMock())
        device_config = MagicMock(type=device_pool_module.HostDevicePoolType.PCI_NIC)

        with patch.object(pool, "_check_passthrough_support"), patch.object(
            device_pool_module.BaseDevicePool, "configure_device_passthrough_pool"
        ):
            pool.configure_device_passthrough_pool([device_config])

        host_node.execute.assert_not_called()
        assert_that(pool._management_route_cleanup_commands).is_empty()

    def test_pool_configuration_opts_in_to_nic_route_guard(self) -> None:
        device_pool_module = _load_device_pool_module()
        for pool_type in (
            device_pool_module.HostDevicePoolType.PCI_NIC,
            device_pool_module.HostDevicePoolType.PCI_GPU,
            device_pool_module.HostDevicePoolType.PCI_NVME,
        ):
            with self.subTest(pool_type=pool_type):
                host_node = MagicMock()
                pool = device_pool_module.LibvirtDevicePool(host_node, MagicMock())
                device_config = MagicMock(type=pool_type)

                with patch.object(pool, "_check_passthrough_support"), patch.object(
                    device_pool_module.BaseDevicePool,
                    "configure_device_passthrough_pool",
                ), patch.object(pool, "_stabilize_management_route") as route_guard:
                    pool.configure_device_passthrough_pool(
                        [device_config], stabilize_management_route=True
                    )

                if pool_type == device_pool_module.HostDevicePoolType.PCI_NIC:
                    route_guard.assert_called_once_with()
                else:
                    route_guard.assert_not_called()
                host_node.execute.assert_not_called()

    def test_request_devices_rearms_management_route_after_cleanup(self) -> None:
        device_pool_module = _load_device_pool_module()
        host_node = MagicMock()
        host_node.execute.return_value = MagicMock(exit_code=0)
        pool = device_pool_module.LibvirtDevicePool(host_node, MagicMock())
        pool_type = device_pool_module.HostDevicePoolType.PCI_NIC
        device = device_pool_module.DeviceAddressSchema(
            domain="0000", bus="19", slot="00", function="0"
        )
        pool.available_host_devices = {pool_type: {"iommu_grp_31": [device]}}
        device_config = MagicMock(type=pool_type)
        cleanup_command = "ip route del 192.0.2.10/32"

        with patch.object(pool, "_check_passthrough_support"), patch.object(
            device_pool_module.BaseDevicePool, "configure_device_passthrough_pool"
        ), patch.object(pool, "_stabilize_management_route") as route_guard:
            pool.configure_device_passthrough_pool(
                [device_config], stabilize_management_route=True
            )
            pool._management_route_cleanup_commands = [cleanup_command]
            node_context = device_pool_module.NodeContext(
                passthrough_devices=[
                    device_pool_module.DevicePassthroughContext(
                        pool_type=pool_type,
                        device_list=pool.request_devices(pool_type, 1),
                    )
                ]
            )
            assert_that(route_guard.call_count).is_equal_to(2)

            pool.release_devices(node_context)
            pool.cleanup()
            pool.request_devices(pool_type, 1)

        assert_that(route_guard.call_count).described_as(
            "A cached pool must protect SSH again after its temporary route is removed"
        ).is_equal_to(3)
        host_node.execute.assert_called_once_with(
            cmd=cleanup_command,
            shell=True,
            sudo=True,
            no_error_log=True,
            expected_exit_code=None,
        )

    def test_request_devices_preserves_pool_when_route_guard_fails(self) -> None:
        device_pool_module = _load_device_pool_module()
        pool = device_pool_module.LibvirtDevicePool(MagicMock(), MagicMock())
        pool_type = device_pool_module.HostDevicePoolType.PCI_NIC
        device = device_pool_module.DeviceAddressSchema(
            domain="0000", bus="19", slot="00", function="0"
        )
        pool.available_host_devices = {pool_type: {"iommu_grp_31": [device]}}
        pool._management_route_guard_enabled = True

        with patch.object(
            pool,
            "_stabilize_management_route",
            side_effect=device_pool_module.LisaException("route guard failed"),
        ), self.assertRaisesRegex(
            device_pool_module.LisaException, "route guard failed"
        ):
            pool.request_devices(pool_type, 1)

        assert_that(pool.available_host_devices[pool_type]).is_equal_to(
            {"iommu_grp_31": [device]}
        )
        assert_that(pool._allocated_device_groups).is_empty()

    def test_request_devices_revalidates_cached_management_route(self) -> None:
        device_pool_module = _load_device_pool_module()
        host_node = MagicMock()
        host_node.execute.return_value = MagicMock(
            exit_code=2, stdout="", stderr="RTNETLINK answers: No such process"
        )
        pool = device_pool_module.LibvirtDevicePool(host_node, MagicMock())
        pool_type = device_pool_module.HostDevicePoolType.PCI_NIC
        device = device_pool_module.DeviceAddressSchema(
            domain="0000", bus="19", slot="00", function="0"
        )
        pool.available_host_devices = {pool_type: {"iommu_grp_31": [device]}}
        pool._management_route_guard_enabled = True
        pool._management_route_cleanup_commands = ["ip route del 192.0.2.10/32"]
        pool.cleanup()

        with patch.object(
            pool,
            "_stabilize_management_route",
            side_effect=device_pool_module.LisaException("SSH route is not protected"),
        ) as route_guard, self.assertRaisesRegex(
            device_pool_module.LisaException, "SSH route is not protected"
        ):
            pool.request_devices(pool_type, 1)

        route_guard.assert_called_once_with()
        assert_that(pool.available_host_devices[pool_type]).is_equal_to(
            {"iommu_grp_31": [device]}
        )
        assert_that(pool._allocated_device_groups).is_empty()

    def test_request_devices_only_guards_opted_in_nic_pools(self) -> None:
        device_pool_module = _load_device_pool_module()
        for pool_type, guard_enabled in (
            (device_pool_module.HostDevicePoolType.PCI_NIC, False),
            (device_pool_module.HostDevicePoolType.PCI_GPU, True),
            (device_pool_module.HostDevicePoolType.PCI_NVME, True),
        ):
            with self.subTest(pool_type=pool_type):
                pool = device_pool_module.LibvirtDevicePool(MagicMock(), MagicMock())
                device = device_pool_module.DeviceAddressSchema(
                    domain="0000", bus="19", slot="00", function="0"
                )
                pool.available_host_devices = {pool_type: {"iommu_grp_31": [device]}}
                pool._management_route_guard_enabled = guard_enabled

                with patch.object(pool, "_stabilize_management_route") as route_guard:
                    devices = pool.request_devices(pool_type, 1)

                route_guard.assert_not_called()
                assert_that(devices).contains_only(device)

    def _create_route_guard_pool(
        self,
    ) -> Tuple["LibvirtDevicePool", MagicMock, _ManagementRouteState]:
        device_pool_module = _load_device_pool_module()
        host_node = MagicMock()
        state = _ManagementRouteState()

        def execute(command: str = "", **kwargs: object) -> MagicMock:
            command = str(kwargs.get("cmd", command))
            result = MagicMock(exit_code=0, stdout="", stderr="")
            if command == 'printf "%s" "$SSH_CONNECTION"':
                result.stdout = f"{state.peer_ip} 50123 198.51.100.214 22"
            elif command == "ip -o -4 addr show":
                result.stdout = (
                    "2: eth0    inet 198.51.100.16/24 scope global eth0\n"
                    "3: eth1    inet 198.51.100.214/24 scope global eth1"
                )
            elif command.startswith("ip -o -4 route get"):
                has_peer_route = any(
                    route.startswith(f"{state.peer_ip}/32 ") for route in state.routes
                )
                interface = (
                    "eth1"
                    if command.endswith("oif eth1")
                    or (has_peer_route and not state.force_passthrough_route)
                    else "eth0"
                )
                result.stdout = (
                    f"{state.peer_ip} via 198.51.100.1 dev {interface} "
                    "src 198.51.100.214 uid 1000"
                )
            elif command.startswith("ip -o -4 route show"):
                result.stdout = "\n".join(
                    route
                    for route in state.routes
                    if route.startswith(f"{state.peer_ip}/32 ")
                )
            elif command.startswith("ip route add "):
                if state.fail_add:
                    raise device_pool_module.LisaException("route add failed")
                state.routes.append(command[len("ip route add ") :])
                if state.lose_add_ack:
                    raise SSHException("route add response lost")
            elif command.startswith("ip route del "):
                route = command[len("ip route del ") :]
                if route in state.routes:
                    state.routes.remove(route)
                else:
                    result.exit_code = 2
                    result.stderr = "RTNETLINK answers: No such process"
            else:
                raise AssertionError(f"Unexpected host command: {command}")
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
        readlink = host_node.tools[device_pool_module.Readlink]
        readlink.get_canonical_path.return_value = (
            "/sys/devices/pci0000:00/0000:19:00.0"
        )
        return pool, host_node, state

    def test_stabilize_management_route_away_from_passthrough_nic(self) -> None:
        pool, host_node, _ = self._create_route_guard_pool()
        metric = pool._management_route_metric

        pool._stabilize_management_route()

        commands = [call.kwargs["cmd"] for call in host_node.execute.call_args_list]
        self.assertIn(
            "ip route add 192.0.2.10/32 via 198.51.100.1 dev eth1 "
            f"src 198.51.100.214 proto static metric {metric}",
            commands,
        )
        self.assertEqual(
            [
                "ip route del 192.0.2.10/32 via 198.51.100.1 dev eth1 "
                f"src 198.51.100.214 proto static metric {metric}"
            ],
            pool._management_route_cleanup_commands,
        )
        self.assertGreaterEqual(metric, 2**31)
        self.assertLess(metric, 2**32)

        pool.cleanup()

        commands = [call.kwargs["cmd"] for call in host_node.execute.call_args_list]
        self.assertIn(
            "ip route del 192.0.2.10/32 via 198.51.100.1 dev eth1 "
            f"src 198.51.100.214 proto static metric {metric}",
            commands,
        )
        self.assertEqual([], pool._management_route_cleanup_commands)

    def test_lost_route_add_acknowledgement_retains_cleanup_intent(self) -> None:
        pool, _, state = self._create_route_guard_pool()
        state.lose_add_ack = True

        with self.assertRaisesRegex(SSHException, "route add response lost"):
            pool._stabilize_management_route()

        assert_that(state.routes).is_length(1)
        assert_that(pool._management_route_cleanup_commands).is_length(1)

        pool.cleanup()

        assert_that(state.routes).is_empty()
        assert_that(pool._management_route_cleanup_commands).is_empty()

    def test_failed_route_add_cleanup_preserves_operator_route(self) -> None:
        device_pool_module = _load_device_pool_module()
        pool, _, state = self._create_route_guard_pool()
        operator_route = (
            "192.0.2.10/32 via 198.51.100.1 dev eth1 " "src 198.51.100.214 proto static"
        )
        build_command = pool._get_management_route_command

        def insert_operator_route(
            peer_ip: str, host_ip: str, management_interface: str
        ) -> str:
            state.routes.append(operator_route)
            state.fail_add = True
            return build_command(peer_ip, host_ip, management_interface)

        with patch.object(
            pool, "_get_management_route_command", side_effect=insert_operator_route
        ), self.assertRaisesRegex(device_pool_module.LisaException, "route add failed"):
            pool._stabilize_management_route()

        pool.cleanup()

        assert_that(state.routes).contains_only(operator_route)

    def test_management_route_guard_does_not_adopt_existing_peer_route(self) -> None:
        pool, host_node, state = self._create_route_guard_pool()
        operator_route = (
            "192.0.2.10/32 via 198.51.100.1 dev eth1 " "src 198.51.100.214 proto static"
        )
        state.routes.append(operator_route)

        pool._stabilize_management_route()
        pool.cleanup()

        assert_that(state.routes).contains_only(operator_route)
        assert_that(pool._management_route_cleanup_commands).is_empty()
        commands = [call.kwargs["cmd"] for call in host_node.execute.call_args_list]
        self.assertFalse(
            any(
                "route add" in command or "route del" in command for command in commands
            )
        )

    def test_request_devices_rejects_route_still_using_passthrough_nic(self) -> None:
        device_pool_module = _load_device_pool_module()
        pool, _, state = self._create_route_guard_pool()
        pool_type = device_pool_module.HostDevicePoolType.PCI_NIC
        available_devices = dict(pool.available_host_devices[pool_type])
        pool._management_route_guard_enabled = True
        state.force_passthrough_route = True

        with self.assertRaisesRegex(device_pool_module.LisaException, "still uses"):
            pool.request_devices(pool_type, 1)

        assert_that(pool.available_host_devices[pool_type]).is_equal_to(
            available_devices
        )
        assert_that(pool._allocated_device_groups).is_empty()
        assert_that(state.routes).is_length(1)

        pool.cleanup()

        assert_that(state.routes).is_empty()

    def test_management_route_cleanup_tracks_multiple_ssh_peers(self) -> None:
        pool, _, state = self._create_route_guard_pool()

        pool._stabilize_management_route()
        state.peer_ip = "192.0.2.11"
        pool._stabilize_management_route()

        assert_that(state.routes).is_length(2)
        assert_that(pool._management_route_cleanup_commands).is_length(2)

        pool.cleanup()

        assert_that(state.routes).is_empty()
        assert_that(pool._management_route_cleanup_commands).is_empty()

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
        self.assertEqual([], pool._management_route_cleanup_commands)
        host_node.tools[
            device_pool_module.Readlink
        ].get_canonical_path.assert_not_called()

    def test_management_route_cleanup_waits_for_all_nics(self) -> None:
        device_pool_module = _load_device_pool_module()
        host_node = MagicMock()
        host_node.execute.return_value = MagicMock(exit_code=0)
        pool = device_pool_module.LibvirtDevicePool(host_node, MagicMock())
        pool_type = device_pool_module.HostDevicePoolType.PCI_NIC
        pool.available_host_devices = {
            pool_type: {
                "iommu_grp_31": [
                    device_pool_module.DeviceAddressSchema(
                        domain="0000", bus="19", slot="00", function="0"
                    )
                ],
                "iommu_grp_32": [
                    device_pool_module.DeviceAddressSchema(
                        domain="0000", bus="19", slot="00", function="1"
                    )
                ],
            }
        }
        node_contexts = []
        for _group in list(pool.available_host_devices[pool_type]):
            node_contexts.append(
                device_pool_module.NodeContext(
                    passthrough_devices=[
                        device_pool_module.DevicePassthroughContext(
                            pool_type=pool_type,
                            device_list=pool.request_devices(pool_type, 1),
                        )
                    ]
                )
            )
        cleanup_command = "ip route del 192.0.2.10/32"
        pool._management_route_cleanup_commands = [cleanup_command]

        pool.cleanup()
        host_node.execute.assert_not_called()

        pool.release_devices(node_contexts[0])
        pool.cleanup()

        host_node.execute.assert_not_called()
        assert_that(pool._management_route_cleanup_commands).described_as(
            "The remaining passthrough VM still needs the SSH route guard"
        ).is_equal_to([cleanup_command])

        pool.release_devices(node_contexts[1])
        pool.cleanup()

        host_node.execute.assert_called_once_with(
            cmd=cleanup_command,
            shell=True,
            sudo=True,
            no_error_log=True,
            expected_exit_code=None,
        )
        assert_that(pool._management_route_cleanup_commands).is_empty()

    def test_management_route_cleanup_tolerates_disconnected_host(self) -> None:
        device_pool_module = _load_device_pool_module()
        host_node = MagicMock()
        host_node.execute.side_effect = SSHException("SSH session not active")
        pool = device_pool_module.LibvirtDevicePool(host_node, MagicMock())
        pool._management_route_cleanup_commands = ["ip route del 192.0.2.10/32"]

        pool.cleanup()

        self.assertEqual(
            ["ip route del 192.0.2.10/32"], pool._management_route_cleanup_commands
        )
        host_node.log.debug.assert_called_once()

    def test_management_route_cleanup_retries_only_failed_removals(self) -> None:
        device_pool_module = _load_device_pool_module()
        host_node = MagicMock()
        host_node.execute.side_effect = [
            SSHException("cleanup response lost"),
            MagicMock(exit_code=0),
        ]
        pool = device_pool_module.LibvirtDevicePool(host_node, MagicMock())
        failed_command = "ip route del 192.0.2.10/32"
        successful_command = "ip route del 192.0.2.11/32"
        pool._management_route_cleanup_commands = [failed_command, successful_command]

        pool.cleanup()

        assert_that(pool._management_route_cleanup_commands).is_equal_to(
            [failed_command]
        )
        assert_that(host_node.execute.call_count).is_equal_to(2)
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
