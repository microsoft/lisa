# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path, PurePath, PurePosixPath
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, Tuple, cast
from unittest import TestCase
from unittest.mock import MagicMock, patch

import yaml

from lisa.sut_orchestrator.openvmm.context import NodeContext
from lisa.sut_orchestrator.openvmm.node import OpenVmmController, OpenVmmGuestNode
from lisa.sut_orchestrator.openvmm.schema import (
    OPENVMM_NETWORK_MODE_TAP,
    OpenVmmGuestNodeSchema,
    OpenVmmNetworkSchema,
    OpenVmmUefiSchema,
)
from lisa.tools import Ip, Kill, Mkdir
from lisa.util import LisaException


class OpenVmmNodeTestCase(TestCase):
    def _create_controller(
        self,
    ) -> Tuple[OpenVmmController, MagicMock, MagicMock, MagicMock]:
        shell_copy = MagicMock()
        kill_by_pid = MagicMock()
        guest_log = MagicMock()
        # execute() returns a result with exit_code=0 so that cache freshness
        # checks (test -f ...) appear to succeed and the cache is reused.
        execute_result = SimpleNamespace(exit_code=0, stderr="", stdout="")
        host_node = SimpleNamespace(
            is_remote=True,
            execute=MagicMock(return_value=execute_result),
            get_pure_path=PurePosixPath,
            shell=SimpleNamespace(copy=shell_copy),
            tools={Kill: SimpleNamespace(by_pid=kill_by_pid)},
        )
        controller = OpenVmmController(cast(Any, host_node), cast(Any, guest_log))
        return controller, shell_copy, kill_by_pid, guest_log

    def test_resolve_guest_artifact_path_uses_unique_names(self) -> None:
        controller, shell_copy, _, _ = self._create_controller()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_dir = root / "first"
            second_dir = root / "second"
            first_dir.mkdir()
            second_dir.mkdir()
            first = first_dir / "disk.img"
            second = second_dir / "disk.img"
            first.write_text("first")
            second.write_text("second")

            first_destination = controller.resolve_guest_artifact_path(
                str(first),
                is_remote_path=False,
                working_path=PurePath("/var/tmp/openvmm"),
            )
            second_destination = controller.resolve_guest_artifact_path(
                str(second),
                is_remote_path=False,
                working_path=PurePath("/var/tmp/openvmm"),
            )

        self.assertNotEqual(first_destination, second_destination)
        self.assertEqual(2, shell_copy.call_count)

    def test_resolve_guest_artifact_path_reuses_host_cache(self) -> None:
        controller, shell_copy, _, _ = self._create_controller()
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "guest.raw"
            source.write_text("disk")

            first_destination = controller.resolve_guest_artifact_path(
                str(source),
                is_remote_path=False,
                working_path=PurePath("/var/tmp/openvmm/g0"),
            )
            second_destination = controller.resolve_guest_artifact_path(
                str(source),
                is_remote_path=False,
                working_path=PurePath("/var/tmp/openvmm/g1"),
            )

        self.assertNotEqual(first_destination, second_destination)
        self.assertEqual(1, shell_copy.call_count)

    def test_stop_node_kills_process_after_wait_timeout(self) -> None:
        controller, _, kill_by_pid, guest_log = self._create_controller()
        node = SimpleNamespace(
            is_connected=False,
            runbook=SimpleNamespace(network=OpenVmmNetworkSchema()),
        )
        node_context = NodeContext(process_id="1234")

        with patch(
            "lisa.sut_orchestrator.openvmm.node.get_node_context",
            return_value=node_context,
        ), patch.object(
            controller,
            "_wait_for_process_exit",
            side_effect=LisaException("timeout"),
        ):
            controller.stop_node(cast(Any, node), wait=True)

        kill_by_pid.assert_called_once_with(
            "1234",
            ignore_not_exist=True,
        )
        self.assertEqual("", node_context.process_id)
        guest_log.info.assert_called_once_with(
            "timeout Forcing OpenVMM process '1234' to stop."
        )

    def test_launch_uses_host_pure_path_for_cwd(self) -> None:
        controller, _, _, _ = self._create_controller()
        openvmm = MagicMock()
        openvmm.build_command.return_value = "openvmm --uefi"
        openvmm.launch_vm.return_value = "1234"
        node = SimpleNamespace(
            runbook=SimpleNamespace(
                openvmm_binary="/usr/local/bin/openvmm",
                network=SimpleNamespace(mode="user", consomme_cidr=""),
                serial=SimpleNamespace(mode="file"),
                extra_args=[],
            ),
            capability=SimpleNamespace(core_count=1, memory_mb=1024),
            log=MagicMock(),
        )
        node_context = NodeContext(
            working_path="/var/tmp/openvmm-host-g0",
            uefi_firmware_path="/var/tmp/MSVM.fd",
            disk_img_path="/var/tmp/guest.img",
            console_log_file_path="/var/tmp/openvmm-console.log",
            launcher_log_file_path="/var/tmp/openvmm-launcher.log",
            launcher_stderr_log_file_path="/var/tmp/openvmm-launcher.stderr.log",
        )

        with patch.object(controller, "get_openvmm_tool", return_value=openvmm), patch(
            "lisa.sut_orchestrator.openvmm.node.get_node_context",
            return_value=node_context,
        ), patch.object(controller, "_ensure_process_running"):
            controller.launch(cast(Any, node), cast(Any, node.log))

        openvmm.launch_vm.assert_called_once_with(
            openvmm.launch_vm.call_args.args[0],
            cwd=PurePosixPath("/var/tmp/openvmm-host-g0"),
            sudo=False,
        )

    def test_create_effective_network_derives_unique_tap_settings(self) -> None:
        controller, _, _, _ = self._create_controller()
        network = OpenVmmNetworkSchema(
            mode=OPENVMM_NETWORK_MODE_TAP,
            tap_name="tap0",
            bridge_name="ovmbr0",
            tap_host_cidr="10.0.0.1/24",
            guest_address="10.0.0.2",
            consomme_cidr="10.0.0.0/24",
            forward_ssh_port=True,
            forwarded_port=60022,
        )

        first_guest_network = controller.create_effective_network(network, 0)
        third_guest_network = controller.create_effective_network(network, 2)

        self.assertEqual("tap0", first_guest_network.tap_name)
        self.assertEqual("ovmbr0", first_guest_network.bridge_name)
        self.assertEqual("10.0.0.1/24", first_guest_network.tap_host_cidr)
        self.assertEqual("10.0.0.2", first_guest_network.guest_address)
        self.assertEqual(60022, first_guest_network.forwarded_port)
        self.assertEqual("tap2", third_guest_network.tap_name)
        self.assertEqual("ovmbr2", third_guest_network.bridge_name)
        self.assertEqual("10.0.2.1/24", third_guest_network.tap_host_cidr)
        self.assertEqual("10.0.2.2", third_guest_network.guest_address)
        self.assertEqual("10.0.2.0/24", third_guest_network.consomme_cidr)
        self.assertEqual(60024, third_guest_network.forwarded_port)
        self.assertEqual("tap0", network.tap_name)
        self.assertEqual("10.0.0.1/24", network.tap_host_cidr)

    def test_tap_network_rejects_invalid_interface_names(self) -> None:
        invalid_networks = [
            {"tap_name": "tap 0"},
            {"tap_name": "tap0", "bridge_name": "br!dge0"},
        ]

        for invalid_network in invalid_networks:
            with self.subTest(invalid_network=invalid_network), self.assertRaises(
                LisaException
            ):
                OpenVmmNetworkSchema(
                    mode=OPENVMM_NETWORK_MODE_TAP,
                    **invalid_network,
                )

    def test_enable_ssh_forwarding_allows_openvmm_guest_subnet_routing(
        self,
    ) -> None:
        bridge_name = "ovmbr1"
        guest_address = "10.0.1.2"
        tap_host_cidr = "10.0.1.1/24"
        execute_result = SimpleNamespace(exit_code=0, stderr="", stdout="0")
        host_node = SimpleNamespace(
            is_remote=True,
            execute=MagicMock(return_value=execute_result),
            tools={Ip: SimpleNamespace(get_default_route_info=lambda: ("eth0", ""))},
        )
        controller = OpenVmmController(cast(Any, host_node), MagicMock())
        node_context = NodeContext(guest_address=guest_address, ssh_port=22)
        network = OpenVmmNetworkSchema(
            mode=OPENVMM_NETWORK_MODE_TAP,
            tap_name="tap1",
            bridge_name=bridge_name,
            tap_host_cidr=tap_host_cidr,
            guest_address=guest_address,
            forward_ssh_port=True,
            forwarded_port=60023,
        )

        controller._enable_ssh_forwarding(node_context, guest_address, network)
        controller._disable_ssh_forwarding_context(node_context, network)

        commands = [call.args[0] for call in host_node.execute.call_args_list]
        self.assertTrue(
            any(
                f"iptables -C FORWARD -i {bridge_name} -o eth0 -j ACCEPT" in command
                for command in commands
            )
        )
        self.assertTrue(
            any(
                f"iptables -D FORWARD -i {bridge_name} -o eth0 -j ACCEPT" in command
                for command in commands
            )
        )
        self.assertFalse(
            any(
                f"iptables -C FORWARD -i {bridge_name} -j ACCEPT" in command
                for command in commands
            )
        )

    def test_create_node_cloud_init_iso_skips_root_resize_for_non_raw_disk(
        self,
    ) -> None:
        controller, shell_copy, _, _ = self._create_controller()
        node = SimpleNamespace(
            runbook=OpenVmmGuestNodeSchema(
                uefi=OpenVmmUefiSchema(firmware_path="/tmp/MSVM.fd"),
                disk_img="/tmp/guest.vhd",
                cloud_init=SimpleNamespace(extra_user_data=[{"runcmd": ["true"]}]),
                network=OpenVmmNetworkSchema(connection_address="127.0.0.1"),
            ),
        )
        node_context = NodeContext(
            vm_name="g0",
            disk_img_path="/var/tmp/guest.vhd",
            cloud_init_file_path="/var/tmp/cloud-init.iso",
        )

        with patch(
            "lisa.sut_orchestrator.openvmm.node.get_node_context",
            return_value=node_context,
        ), patch.object(controller, "_create_iso") as create_iso:
            controller.create_node_cloud_init_iso(cast(Any, node))

        user_data = yaml.safe_load(
            create_iso.call_args.args[1][0][1].split("\n", 1)[1]
        )
        self.assertNotIn("growpart", user_data)
        self.assertNotIn("resize_rootfs", user_data)
        shell_copy.assert_called_once()

    def test_ensure_minimum_raw_disk_size_grows_raw_image(self) -> None:
        controller, _, _, _ = self._create_controller()

        controller.ensure_minimum_raw_disk_size("/var/tmp/guest.raw", 16)

        execute = cast(MagicMock, controller.host_node.execute)
        command = execute.call_args.args[0]
        self.assertIn("stat -c %s /var/tmp/guest.raw", command)
        self.assertIn("truncate -s 16G /var/tmp/guest.raw", command)

    def test_ensure_minimum_raw_disk_size_skips_non_raw_image(self) -> None:
        controller, _, _, _ = self._create_controller()

        controller.ensure_minimum_raw_disk_size("/var/tmp/guest.vhd", 16)

        cast(MagicMock, controller.host_node.execute).assert_not_called()

    def test_provision_uses_host_pure_path_for_working_directory(self) -> None:
        host_node = SimpleNamespace(
            name="host",
            initialize=MagicMock(),
            get_pure_path=PurePosixPath,
            tools={Mkdir: SimpleNamespace(create_directory=MagicMock())},
        )
        controller = MagicMock()
        controller.get_openvmm_tool.return_value = SimpleNamespace(exists=True)
        controller.resolve_guest_artifact_path.side_effect = [
            "/var/tmp/host-g0/MSVM.fd",
            "/var/tmp/host-g0/guest.img",
        ]
        node = SimpleNamespace(
            parent=host_node,
            name="g0",
            index=0,
            log=MagicMock(),
            runbook=OpenVmmGuestNodeSchema(
                uefi=OpenVmmUefiSchema(firmware_path="/tmp/MSVM.fd"),
                disk_img="/tmp/guest.img",
                network=OpenVmmNetworkSchema(connection_address="127.0.0.1"),
            ),
            _openvmm_controller=controller,
        )
        node_context = NodeContext()

        with patch(
            "lisa.sut_orchestrator.openvmm.node.get_node_context",
            return_value=node_context,
        ):
            OpenVmmGuestNode._provision(cast(Any, node))

        self.assertEqual("/var/tmp/host-g0", node_context.working_path)
        host_node.tools[Mkdir].create_directory.assert_called_once_with(
            "/var/tmp/host-g0"
        )
        controller.ensure_minimum_raw_disk_size.assert_not_called()
