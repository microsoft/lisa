# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path, PurePath, PurePosixPath
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, Tuple, cast
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.sut_orchestrator.openvmm.context import NodeContext
from lisa.sut_orchestrator.openvmm.node import OpenVmmController, OpenVmmGuestNode
from lisa.sut_orchestrator.openvmm.schema import (
    OpenVmmGuestNodeSchema,
    OpenVmmNetworkSchema,
    OpenVmmUefiSchema,
)
from lisa.tools import Kill, Mkdir
from lisa.util import LisaException


class OpenVmmNodeTestCase(TestCase):
    def _create_controller(
        self,
    ) -> Tuple[OpenVmmController, MagicMock, MagicMock, MagicMock]:
        shell_copy = MagicMock()
        kill_by_pid = MagicMock()
        guest_log = MagicMock()
        host_node = SimpleNamespace(
            is_remote=True,
            get_pure_path=PurePosixPath,
            shell=SimpleNamespace(copy=shell_copy),
            tools={Kill: SimpleNamespace(by_pid=kill_by_pid)},
        )
        guest_node = SimpleNamespace(parent=host_node, log=guest_log)
        controller = OpenVmmController(cast(Any, guest_node))
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
