# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from unittest.mock import MagicMock

import yaml

from lisa.util import LisaException
from lisa.tools.openvmm import OpenVmmLaunchConfig
from lisa.sut_orchestrator.openvmm.schema import OpenVmmNetworkSchema
from lisa.sut_orchestrator.openvmm.node import _get_tap_host_interface_name
from lisa.sut_orchestrator.openvmm.node import NeighborTableResolver
from lisa.sut_orchestrator.openvmm.node import OpenVmmController
from lisa.sut_orchestrator.openvmm.node import OpenVmmGuestNode
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

    def test_ensure_tap_dhcp_input_allowed_inserts_missing_rule(self) -> None:
        controller = OpenVmmController.__new__(OpenVmmController)
        controller.host_node = MagicMock()
        controller.host_node.execute.side_effect = [
            SimpleNamespace(stdout="", stderr="", exit_code=0),
            SimpleNamespace(stdout="", stderr="", exit_code=1),
            SimpleNamespace(stdout="", stderr="", exit_code=0),
        ]
        node_context = SimpleNamespace(tap_dhcp_input_rule_added=False)

        controller._ensure_tap_dhcp_input_allowed("ovmbr0", node_context)

        self.assertTrue(node_context.tap_dhcp_input_rule_added)
        self.assertEqual(3, controller.host_node.execute.call_count)
        self.assertIn(
            "iptables -C INPUT -i ovmbr0 -p udp -m udp --dport 67 -j ACCEPT",
            controller.host_node.execute.call_args_list[1].args[0],
        )
        self.assertIn(
            "iptables -I INPUT -i ovmbr0 -p udp -m udp --dport 67 -j ACCEPT",
            controller.host_node.execute.call_args_list[2].args[0],
        )

    def test_ensure_tap_dhcp_input_allowed_skips_existing_rule(self) -> None:
        controller = OpenVmmController.__new__(OpenVmmController)
        controller.host_node = MagicMock()
        controller.host_node.execute.side_effect = [
            SimpleNamespace(stdout="", stderr="", exit_code=0),
            SimpleNamespace(stdout="", stderr="", exit_code=0),
        ]
        node_context = SimpleNamespace(tap_dhcp_input_rule_added=False)

        controller._ensure_tap_dhcp_input_allowed("ovmbr0", node_context)

        self.assertFalse(node_context.tap_dhcp_input_rule_added)
        self.assertEqual(2, controller.host_node.execute.call_count)

    def test_teardown_tap_network_removes_dhcp_input_rule(self) -> None:
        controller = OpenVmmController.__new__(OpenVmmController)
        controller.host_node = MagicMock()
        controller.host_node.execute.return_value = SimpleNamespace(
            stdout="", stderr="", exit_code=0
        )
        node_context = SimpleNamespace(
            tap_dhcp_input_rule_added=True,
            tap_dnsmasq_pid_file="",
            tap_dnsmasq_lease_file="",
            tap_created=False,
            tap_bridge_created=False,
        )

        controller._teardown_tap_network(
            node_context,
            OpenVmmNetworkSchema(mode="tap", tap_name="tap0", bridge_name="ovmbr0"),
        )

        self.assertFalse(node_context.tap_dhcp_input_rule_added)
        self.assertEqual(1, controller.host_node.execute.call_count)
        self.assertIn(
            "iptables -D INPUT -i ovmbr0 -p udp -m udp --dport 67 -j ACCEPT || true",
            controller.host_node.execute.call_args.args[0],
        )

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
            cloud_init_file_path="/tmp/cloud-init.iso",
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
        openvmm.launch_vm.assert_called_once()
        launch_config = openvmm.launch_vm.call_args.args[0]
        self.assertEqual(["/tmp/cloud-init.iso"], launch_config.dvd_disk_paths)
        self.assertTrue(openvmm.launch_vm.call_args.kwargs["sudo"])

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
        self.assertIn("--hv", command)
        self.assertIn("--hypervisor", command)
        self.assertIn("--uefi-firmware", command)
        self.assertIn("--disk", command)
        self.assertIn("--net", command)
        self.assertNotIn("--virtio-net", command)
        self.assertNotIn("--kernel", command)

    def test_openvmm_build_command_adds_cloud_init_iso(self) -> None:
        tool = OpenVmm.__new__(OpenVmm)
        tool._command = "openvmm"

        command = tool.build_command(
            OpenVmmLaunchConfig(
                uefi_firmware_path="/var/tmp/MSVM.fd",
                disk_img_path="/var/tmp/ubuntu.img",
                dvd_disk_paths=["/var/tmp/cloud-init.iso"],
                network_mode="tap",
                tap_name="tap0",
                serial_mode="file",
                serial_path="/var/tmp/serial.log",
            )
        )

        self.assertIn("file:/var/tmp/cloud-init.iso,dvd", command)

    def test_openvmm_launch_vm_uses_sudo_when_requested(self) -> None:
        tool = OpenVmm.__new__(OpenVmm)
        tool._command = "/usr/local/bin/openvmm"
        tool.node = MagicMock()
        tool.node.execute.return_value = SimpleNamespace(stdout="1234\n")

        process_id = tool.launch_vm(
            OpenVmmLaunchConfig(
                uefi_firmware_path="/var/tmp/MSVM.fd",
                disk_img_path="/var/tmp/guest.img",
                network_mode="tap",
                tap_name="tap0",
                serial_mode="file",
                serial_path="/var/tmp/serial.log",
                stdout_path="/var/tmp/openvmm-launcher.log",
                stderr_path="/var/tmp/openvmm-launcher.log",
            ),
            sudo=True,
        )

        self.assertEqual("1234", process_id)
        self.assertEqual(1, tool.node.execute.call_count)
        self.assertTrue(tool.node.execute.call_args.kwargs["sudo"])

    def test_openvmm_launch_vm_prefers_script_wrapper(self) -> None:
        tool = OpenVmm.__new__(OpenVmm)
        tool._command = "/usr/local/bin/openvmm"
        tool.node = MagicMock()
        tool.node.execute.return_value = SimpleNamespace(stdout="1234\n")

        tool.launch_vm(
            OpenVmmLaunchConfig(
                uefi_firmware_path="/var/tmp/MSVM.fd",
                disk_img_path="/var/tmp/guest.img",
                network_mode="tap",
                tap_name="tap0",
                serial_mode="file",
                serial_path="/var/tmp/serial.log",
                stdout_path="/var/tmp/openvmm-launcher.log",
                stderr_path="/var/tmp/openvmm-launcher.log",
            )
        )

        shell_command = tool.node.execute.call_args.args[0]
        self.assertIn("if command -v script >/dev/null 2>&1; then", shell_command)
        self.assertIn("nohup sh -c", shell_command)
        self.assertIn("tail -f /dev/null | script -qefc", shell_command)
        self.assertIn("/dev/null", shell_command)
        self.assertIn("else nohup /usr/local/bin/openvmm", shell_command)

    def test_cloud_init_iso_uses_valid_password_schema_and_instance_id(self) -> None:
        controller = OpenVmmController.__new__(OpenVmmController)
        controller.host_node = MagicMock()
        controller.host_node.shell = MagicMock()

        node = MagicMock()
        node.runbook = SimpleNamespace(
            username="lisatest",
            password="guest-password",
            private_key_file="",
        )

        node_context = SimpleNamespace(
            vm_name="openvmm-manual",
            cloud_init_file_path="/tmp/cloud-init.iso",
            extra_cloud_init_user_data=[],
        )

        with patch(
            "lisa.sut_orchestrator.openvmm.node.get_node_context",
            return_value=node_context,
        ):
            with patch.object(
                OpenVmmController, "_create_iso", autospec=True
            ) as create_iso:
                controller.create_node_cloud_init_iso(node)

        files = {
            path: contents for path, contents in create_iso.call_args.args[2]
        }
        user_data = yaml.safe_load(files["/user-data"].removeprefix("#cloud-config\n"))
        meta_data = yaml.safe_load(files["/meta-data"])

        user = user_data["users"][1]
        self.assertEqual("lisatest", user["name"])
        self.assertFalse(user["lock_passwd"])
        self.assertEqual("guest-password", user["plain_text_passwd"])
        self.assertTrue(user_data["ssh_pwauth"])
        self.assertNotIn("chpasswd", user_data)
        self.assertEqual("openvmm-manual", meta_data["local-hostname"])
        self.assertRegex(
            meta_data["instance-id"], r"^openvmm-manual-[0-9a-f]{32}$"
        )

    def test_start_node_refreshes_cloud_init_iso_before_launch(self) -> None:
        controller = OpenVmmController.__new__(OpenVmmController)
        node = MagicMock()
        node.runbook = SimpleNamespace(cloud_init=SimpleNamespace())
        node.log = MagicMock()

        with patch.object(
            OpenVmmController, "create_node_cloud_init_iso", autospec=True
        ) as create_node_cloud_init_iso:
            with patch.object(OpenVmmController, "launch", autospec=True) as launch:
                with patch.object(
                    OpenVmmController, "configure_connection", autospec=True
                ) as configure_connection:
                    controller.start_node(node)

        create_node_cloud_init_iso.assert_called_once_with(controller, node)
        launch.assert_called_once_with(controller, node, node.log)
        configure_connection.assert_called_once_with(controller, node, node.log)

    def test_cleanup_node_artifacts_removes_working_directory(self) -> None:
        controller = OpenVmmController.__new__(OpenVmmController)
        controller.host_node = MagicMock()
        controller.host_node.execute.return_value = SimpleNamespace(
            stdout="", stderr="", exit_code=0
        )
        node = MagicMock()
        node_context = SimpleNamespace(
            working_path="/var/tmp/openvmm-guest",
            uefi_firmware_path="/var/tmp/openvmm-guest/MSVM.fd",
            disk_img_path="/var/tmp/openvmm-guest/guest.img",
            cloud_init_file_path="/var/tmp/openvmm-guest/cloud-init.iso",
            console_log_file_path="/var/tmp/openvmm-guest/openvmm-console.log",
            launcher_log_file_path="/var/tmp/openvmm-guest/openvmm-launcher.log",
        )

        with patch(
            "lisa.sut_orchestrator.openvmm.node.get_node_context",
            return_value=node_context,
        ):
            controller.cleanup_node_artifacts(node)

        controller.host_node.execute.assert_called_once_with(
            "rm -rf /var/tmp/openvmm-guest",
            shell=True,
            sudo=True,
            expected_exit_code=0,
        )
        self.assertEqual("", node_context.working_path)
        self.assertEqual("", node_context.disk_img_path)
        self.assertEqual("", node_context.cloud_init_file_path)

    def test_guest_cleanup_removes_openvmm_artifacts(self) -> None:
        node = OpenVmmGuestNode.__new__(OpenVmmGuestNode)
        node.log = MagicMock()
        node._openvmm_controller = MagicMock()

        with patch("lisa.node.RemoteNode.cleanup", autospec=True) as remote_cleanup:
            OpenVmmGuestNode.cleanup(node)

        node._openvmm_controller.stop_node.assert_called_once_with(node, wait=False)
        node._openvmm_controller.cleanup_node_artifacts.assert_called_once_with(node)
        remote_cleanup.assert_called_once_with(node)
