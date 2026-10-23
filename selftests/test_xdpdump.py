# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Type
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.executable import ExecutableResult
from lisa.node import Node
from lisa.util import LisaException, SkippedException
from lisa.util.logger import get_logger
from lisa.util.package import import_package
from lisa.util.process import Process

if TYPE_CHECKING:
    from lisa.microsoft.testsuites.xdp.xdpdump import XdpDump


class XdpDumpResultTestCase(TestCase):
    _tool_type: Type[XdpDump]
    _unsupported_virtio = (
        "Kernel error message: virtio_net: Can't set XDP while host is "
        "implementing GRO_HW/CSUM, disable GRO_HW/CSUM first\n"
        "error setting fd onto xdp\n"
    )

    @classmethod
    def setUpClass(cls) -> None:
        module_path = (
            Path(__file__).parent.parent
            / "lisa"
            / "microsoft"
            / "testsuites"
            / "xdp"
            / "xdpdump.py"
        )
        import_package(module_path, "microsoft.testsuites.xdp", enable_log=False)
        cls._tool_type = import_module("microsoft.testsuites.xdp.xdpdump").XdpDump

    def setUp(self) -> None:
        node = MagicMock(spec=Node)
        node.log = get_logger("xdpdump-test")
        self.tool = self._tool_type(node)
        self.process = MagicMock(spec=Process)
        self.process.is_running.return_value = False
        restore_patch = patch.object(self.tool, "_restore_lro")
        self.restore = restore_patch.start()
        self.addCleanup(restore_patch.stop)

    def _wait_for_result(
        self, stdout: str = "", stderr: str = "", exit_code: int = 255
    ) -> ExecutableResult:
        self.process.wait_result.return_value = ExecutableResult(
            _stdout=stdout,
            _stderr=stderr,
            exit_code=exit_code,
            cmd="xdpdump",
            _id_="xdp-test",
            elapsed=1,
        )
        return self.tool.wait_result("eth0", self.process)

    def test_unsupported_virtio_negotiation_is_na_after_cleanup(self) -> None:
        for stdout, stderr in (
            (self._unsupported_virtio, ""),
            ("", self._unsupported_virtio),
        ):
            with self.subTest(stream="stdout" if stdout else "stderr"):
                self.restore.reset_mock()
                with self.assertRaisesRegex(SkippedException, "CTRL_GUEST_OFFLOADS"):
                    self._wait_for_result(stdout=stdout, stderr=stderr)

                self.restore.assert_called_once_with("eth0")

    def test_unrelated_attach_failure_is_not_skipped(self) -> None:
        with self.assertRaisesRegex(AssertionError, "permission denied"):
            self._wait_for_result(stderr="libbpf: permission denied")

        self.restore.assert_called_once_with("eth0")

    def test_success_and_expected_timeout_keep_program_output(self) -> None:
        for exit_code in (0, 124):
            with self.subTest(exit_code=exit_code):
                result = self._wait_for_result(
                    stdout="unloading xdp program...\n", exit_code=exit_code
                )

                self.assertEqual(result.stdout, "unloading xdp program...\n")

    def test_cleanup_failure_is_not_hidden_by_unsupported_device(self) -> None:
        self.restore.side_effect = LisaException("restore failed")

        with self.assertRaisesRegex(LisaException, "restore failed"):
            self._wait_for_result(stdout=self._unsupported_virtio)
