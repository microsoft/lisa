# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from unittest.mock import MagicMock

from lisa.util import LisaException
from lisa.tools.openvmm import OpenVmmLaunchConfig
from lisa.sut_orchestrator.openvmm.schema import OpenVmmNetworkSchema
from lisa.sut_orchestrator.openvmm.node import _get_tap_host_interface_name
from lisa.sut_orchestrator.openvmm.node import NeighborTableResolver
from lisa.sut_orchestrator.openvmm.node import OpenVmmController
from lisa.node import Node
from lisa.tools import Ip
from lisa.tools import OpenVmm


class _FakeIpTool:
    def __init__(self, result: SimpleNamespace) -> None:
        self._result = result

    def run(self, *args: object, **kwargs: object) -> SimpleNamespace:
        return self._result


class _FakeTools:
    def __init__(self, ip_tool: _FakeIpTool) -> None:
        self._ip_tool = ip_tool

    def __getitem__(self, key: object) -> _FakeIpTool:
        assert key is Ip
        return self._ip_tool


class OpenVmmNodeTestCase(TestCase):
    def test_neighbor_resolver_returns_empty_when_tap_device_is_missing(self) -> None:
        host = MagicMock(spec=Node)
        host.tools = _FakeTools(
            _FakeIpTool(
                SimpleNamespace(
                    stdout='Cannot find device "tap0"',
                    stderr="",
                    exit_code=1,
                )
            )
        )

        resolver = NeighborTableResolver()

        addresses = resolver._get_candidate_addresses(host, "tap0")

        self.assertEqual([], addresses)

    def test_tap_network_config_uses_first_available_guest_ip(self) -> None:
        controller = OpenVmmController.__new__(OpenVmmController)

        gateway, dhcp_range = controller._get_tap_network_config(
            OpenVmmNetworkSchema(
                mode="tap",
                tap_name="tap0",
                tap_host_cidr="10.0.0.1/24",
            )
        )

        self.assertEqual("10.0.0.1", gateway)
        self.assertEqual("10.0.0.2,10.0.0.2", dhcp_range)

    def test_bridge_backed_tap_uses_bridge_interface_for_host_network(self) -> None:
        interface_name = _get_tap_host_interface_name(
            OpenVmmNetworkSchema(
                mode="tap",
                tap_name="ovmtap0",
                bridge_name="virbr0",
            )
        )

        self.assertEqual("virbr0", interface_name)

    def test_tap_guest_address_is_derived_from_host_cidr(self) -> None:
        controller = OpenVmmController.__new__(OpenVmmController)
        with patch.object(
            OpenVmmController, "_wait_for_tap_lease", autospec=True
        ) as wait_for_tap_lease:
            guest_address = controller._get_tap_guest_address(
                SimpleNamespace(
                    tap_dnsmasq_lease_file="/var/run/qemu-dnsmasq-tap0.leases"
                ),
                OpenVmmNetworkSchema(
                    mode="tap", tap_name="tap0", tap_host_cidr="10.0.0.1/24"
                ),
                MagicMock(),
            )

        self.assertEqual("10.0.0.2", guest_address)
        wait_for_tap_lease.assert_called_once()

    def test_tap_guest_address_requires_usable_host_cidr(self) -> None:
        controller = OpenVmmController.__new__(OpenVmmController)

        with self.assertRaises(LisaException):
            controller._get_tap_guest_address(
                SimpleNamespace(tap_dnsmasq_lease_file="/var/run/qemu-dnsmasq-tap0.leases"),
                OpenVmmNetworkSchema(mode="tap", tap_name="tap0", tap_host_cidr="10.0.0.1/32"),
                MagicMock(),
            )

    def test_wait_for_tap_lease_fails_with_context_when_lease_missing(self) -> None:
        controller = OpenVmmController.__new__(OpenVmmController)
        controller.host_node = MagicMock()
        controller.host_node.execute.side_effect = [
            SimpleNamespace(stdout="", stderr="", exit_code=0),
            SimpleNamespace(stdout="", stderr="", exit_code=0),
            SimpleNamespace(stdout="console output", stderr="", exit_code=0),
            SimpleNamespace(stdout="launcher output", stderr="", exit_code=0),
        ]

        with patch.object(
            OpenVmmController, "_is_process_running", autospec=True, return_value=True
        ):
            with self.assertRaises(LisaException) as context:
                controller._wait_for_tap_lease(
                    SimpleNamespace(
                        tap_dnsmasq_lease_file="/tmp/openvmm.leases",
                        console_log_file_path="/tmp/openvmm-console.log",
                        launcher_log_file_path="/tmp/openvmm-launcher.log",
                    ),
                    "10.0.0.2",
                    MagicMock(),
                    timeout=0,
                )

        self.assertIn("did not acquire the expected DHCP lease", str(context.exception))
        self.assertIn("console output", str(context.exception))
        self.assertIn("launcher output", str(context.exception))

    def test_wait_for_tap_lease_fails_fast_when_process_exits(self) -> None:
        controller = OpenVmmController.__new__(OpenVmmController)
        controller.host_node = MagicMock()
        controller.host_node.execute.return_value = SimpleNamespace(
            stdout="",
            stderr="",
            exit_code=0,
        )
        with patch.object(
            OpenVmmController, "_is_process_running", autospec=True, return_value=False
        ):
            with patch.object(
                OpenVmmController,
                "_get_openvmm_failure_context",
                autospec=True,
                return_value="process state: openvmm exited",
            ):
                with self.assertRaises(LisaException) as context:
                    controller._wait_for_tap_lease(
                        SimpleNamespace(
                            process_id="1234",
                            tap_dnsmasq_lease_file="/tmp/openvmm.leases",
                        ),
                        "10.0.0.2",
                        MagicMock(),
                        OpenVmmNetworkSchema(mode="tap", tap_name="tap0"),
                        timeout=1,
                    )

        self.assertIn("process exited before the guest acquired", str(context.exception))
        self.assertIn("openvmm exited", str(context.exception))

    def test_launch_fails_when_openvmm_process_exits_immediately(self) -> None:
        controller = OpenVmmController.__new__(OpenVmmController)
        controller.host_node = MagicMock()

        openvmm = MagicMock()
        openvmm.build_command.return_value = "openvmm --uefi"
        openvmm.launch_vm.return_value = "1234"

        node = MagicMock()
        node.runbook = SimpleNamespace(
            openvmm_binary="/usr/local/bin/openvmm",
            network=OpenVmmNetworkSchema(mode="tap", tap_name="tap0"),
            serial=SimpleNamespace(mode="file"),
            extra_args=[],
        )
        node.capability = SimpleNamespace(core_count=2, memory_mb=2048)
        node.log = MagicMock()

        node_context = SimpleNamespace(
            uefi_firmware_path="/tmp/MSVM.fd",
            disk_img_path="/tmp/guest.img",
            console_log_file_path="/tmp/openvmm-console.log",
            launcher_log_file_path="/tmp/openvmm-launcher.log",
            working_path="/tmp",
            command_line="",
            process_id="",
        )

        with patch.object(
            OpenVmmController, "get_openvmm_tool", autospec=True, return_value=openvmm
        ):
            with patch.object(
                OpenVmmController, "_prepare_tap_network", autospec=True
            ):
                with patch.object(
                    OpenVmmController,
                    "_ensure_process_running",
                    autospec=True,
                    side_effect=LisaException("OpenVMM exited"),
                ) as ensure_process_running:
                    with patch(
                        "lisa.sut_orchestrator.openvmm.node.get_node_context",
                        return_value=node_context,
                    ):
                        with self.assertRaises(LisaException):
                            controller.launch(node, MagicMock())

        ensure_process_running.assert_called_once()

    def test_openvmm_build_command_for_uefi_boot(self) -> None:
        tool = OpenVmm.__new__(OpenVmm)
        tool._command = "openvmm"

        command = tool.build_command(
            OpenVmmLaunchConfig(
                uefi_firmware_path="/var/tmp/MSVM.fd",
                disk_img_path="/var/tmp/ubuntu.img",
                network_mode="tap",
                tap_name="tap0",
                serial_mode="file",
                serial_path="/var/tmp/serial.log",
            )
        )

        self.assertIn("--uefi", command)
        self.assertIn("--uefi-firmware", command)
        self.assertIn("--disk", command)
        self.assertNotIn("--kernel", command)