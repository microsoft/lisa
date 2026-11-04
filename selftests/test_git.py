# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import shutil
import subprocess
import uuid
from pathlib import Path, PurePosixPath
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.tools import Gcc, Git, Make, Netperf
from lisa.tools.git import CodeExistsException
from lisa.util import LisaException
from lisa.util.logger import get_logger
from lisa.util.process import ExecutableResult


class GitCloneTestCase(TestCase):
    _cwd = PurePosixPath("/tools")
    _destination = _cwd / "netperf"
    _disconnect = (
        "error: RPC failed; curl 56 GnuTLS recv error (-54): "
        "Error in the pull function.\n"
        "error: 128 bytes of body are still expected\n"
        "fetch-pack: unexpected disconnect while reading sideband packet\n"
        "fatal: early EOF\n"
        "fatal: fetch-pack: invalid index-pack output"
    )

    def setUp(self) -> None:
        self.node = MagicMock()
        self.node.log = get_logger("git_clone_test")
        self.git = Git(self.node)
        run_patch = patch.object(self.git, "run")
        self.clone_run = run_patch.start()
        self.addCleanup(run_patch.stop)
        checkout_patch = patch.object(self.git, "checkout")
        self.checkout = checkout_patch.start()
        self.addCleanup(checkout_patch.stop)
        mark_safe_patch = patch.object(self.git, "_mark_safe")
        mark_safe_patch.start()
        self.addCleanup(mark_safe_patch.stop)
        sleep_patch = patch("retry.api.time.sleep")
        self.sleep = sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

    @staticmethod
    def _result(exit_code: int, stdout: str = "", stderr: str = "") -> ExecutableResult:
        return ExecutableResult(stdout, stderr, exit_code, "git clone", "", 0)

    def test_netperf_recovers_from_receive_disconnect(self) -> None:
        operations = MagicMock()
        operations.attach_mock(self.clone_run, "clone")
        operations.attach_mock(self.node.shell.remove, "remove")
        self.node.shell.exists.side_effect = [False, True, False, False]
        self.clone_run.side_effect = [
            self._result(128, "Cloning into 'netperf'...\n", self._disconnect),
            self._result(0, stderr="Cloning into 'netperf'...\n"),
        ]
        gcc = MagicMock()
        gcc.get_version.return_value = "11.0.0"
        make = MagicMock()
        self.node.tools = {Git: self.git, Gcc: gcc, Make: make}
        self.node.os.get_kernel_information.return_value.hardware_platform = "x86_64"
        self.node.execute.return_value = self._result(0)
        netperf = Netperf(self.node)
        with patch.object(netperf, "_install_dep_packages"), patch.object(
            netperf, "get_tool_path", return_value=self._cwd
        ):
            netperf._install_from_src()

        self.assertEqual(self.clone_run.call_count, 2)
        self.assertTrue(self.clone_run.call_args.kwargs["force_run"])
        self.assertEqual(
            [operation[0] for operation in operations.mock_calls],
            ["clone", "remove", "clone"],
        )
        self.node.shell.remove.assert_called_once_with(
            self._destination, recursive=True
        )
        self.checkout.assert_called_once_with(Netperf.branch, cwd=self._destination)
        make.make_install.assert_called_once_with(self._destination)

    def test_disconnect_exhaustion_cleans_each_partial_clone(self) -> None:
        self.node.shell.exists.side_effect = [
            False,
            True,
            False,
            True,
            False,
            True,
            False,
        ]
        self.clone_run.return_value = self._result(
            128, "Cloning into 'netperf'...\n", self._disconnect
        )

        with self.assertRaisesRegex(LisaException, "fatal: early EOF") as raised:
            self.git.clone(
                "https://example.com/netperf",
                self._cwd,
                dir_name="netperf",
                max_attempts=3,
            )

        self.assertIn("curl 56", str(raised.exception))
        self.assertIn("3 attempts", str(raised.exception))
        self.assertEqual(self.clone_run.call_count, 3)
        self.assertEqual(self.node.shell.remove.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)
        self.checkout.assert_not_called()

    def test_nontransient_errors_fail_without_retries_or_tls_changes(self) -> None:
        for error in (
            "fatal: Authentication failed for 'https://example.com/netperf'",
            "fatal: unable to access repository: The requested URL returned error: 403",
            "fatal: repository 'https://example.com/netperf' not found",
            "fatal: server certificate verification failed",
            "fatal: could not create work tree dir 'netperf': Permission denied",
            "fatal: write error: No space left on device",
            self._disconnect + "\nfatal: Authentication failed",
            self._disconnect.replace("fatal: early EOF\n", ""),
        ):
            with self.subTest(error=error):
                self.node.shell.exists.return_value = False
                self.clone_run.reset_mock()
                self.clone_run.return_value = self._result(128, error)

                with self.assertRaises(LisaException) as raised:
                    self.git.clone(
                        "https://example.com/netperf",
                        self._cwd,
                        dir_name="netperf",
                        max_attempts=3,
                    )

                self.assertIn(error, str(raised.exception))
                self.clone_run.assert_called_once()
                self.node.shell.remove.assert_not_called()
                self.sleep.assert_not_called()

    def test_real_missing_repository_failure_is_preserved(self) -> None:
        workspace = Path(f"git-clone-selftest-{uuid.uuid4().hex}")
        workspace.mkdir()
        self.addCleanup(shutil.rmtree, workspace)
        result = subprocess.run(
            ["git", "clone", str(workspace / "missing"), str(workspace / "checkout")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.node.shell.exists.return_value = False
        self.clone_run.return_value = self._result(
            result.returncode, result.stdout, result.stderr
        )

        with self.assertRaises(LisaException) as raised:
            self.git.clone(
                "https://example.com/netperf",
                self._cwd,
                dir_name="netperf",
                max_attempts=3,
            )

        self.assertIn(result.stderr.strip(), str(raised.exception))
        self.clone_run.assert_called_once()
        self.node.shell.remove.assert_not_called()
        self.sleep.assert_not_called()

    def test_default_clone_does_not_retry_disconnects(self) -> None:
        self.clone_run.return_value = self._result(128, stderr=self._disconnect)

        with self.assertRaisesRegex(LisaException, "fatal: early EOF"):
            self.git.clone("https://example.com/netperf", self._cwd)

        self.clone_run.assert_called_once()
        self.node.shell.exists.assert_not_called()
        self.node.shell.remove.assert_not_called()
        self.sleep.assert_not_called()

    def test_existing_destination_is_preserved(self) -> None:
        for fail_on_exists in (True, False):
            with self.subTest(fail_on_exists=fail_on_exists):
                self.node.shell.exists.return_value = True
                self.clone_run.reset_mock()
                self.clone_run.return_value = self._result(
                    128,
                    "fatal: destination path 'netperf' already exists "
                    "and is not an empty directory.",
                )
                if fail_on_exists:
                    with self.assertRaises(CodeExistsException):
                        self.git.clone(
                            "https://example.com/netperf",
                            self._cwd,
                            dir_name="netperf",
                            max_attempts=3,
                        )
                else:
                    result = self.git.clone(
                        "https://example.com/netperf",
                        self._cwd,
                        dir_name="netperf",
                        fail_on_exists=False,
                        max_attempts=3,
                    )
                    self.assertEqual(result, self._destination)

                self.clone_run.assert_called_once()
                self.node.shell.remove.assert_not_called()
                self.sleep.assert_not_called()

    def test_disconnect_in_preexisting_empty_directory_is_not_retried(self) -> None:
        self.node.shell.exists.return_value = True
        self.clone_run.return_value = self._result(128, stderr=self._disconnect)

        with self.assertRaisesRegex(LisaException, "fatal: early EOF"):
            self.git.clone(
                "https://example.com/netperf",
                self._cwd,
                dir_name="netperf",
                max_attempts=3,
            )

        self.clone_run.assert_called_once()
        self.node.shell.remove.assert_not_called()

    def test_cleanup_failure_stops_retries_and_preserves_clone_error(self) -> None:
        self.node.shell.exists.side_effect = [False, True]
        self.node.shell.remove.side_effect = PermissionError("read-only directory")
        self.clone_run.return_value = self._result(128, stderr=self._disconnect)

        with self.assertRaisesRegex(LisaException, "failed to clean") as raised:
            self.git.clone(
                "https://example.com/netperf",
                self._cwd,
                dir_name="netperf",
                max_attempts=3,
            )

        self.assertIn("fatal: early EOF", str(raised.exception))
        self.assertIn("read-only directory", str(raised.exception))
        self.assertIsInstance(raised.exception.__cause__, PermissionError)
        self.clone_run.assert_called_once()
        self.sleep.assert_not_called()

    def test_checkout_failure_is_not_retried(self) -> None:
        self.node.shell.exists.return_value = False
        self.clone_run.return_value = self._result(
            0, stderr="Cloning into 'netperf'...\n"
        )
        self.checkout.side_effect = LisaException("unknown revision")

        with self.assertRaisesRegex(LisaException, "unknown revision"):
            self.git.clone(
                "https://example.com/netperf",
                self._cwd,
                ref="unknown",
                dir_name="netperf",
                max_attempts=3,
            )

        self.clone_run.assert_called_once()
        self.node.shell.remove.assert_not_called()
        self.sleep.assert_not_called()

    def test_incomplete_cleanup_prevents_another_attempt(self) -> None:
        self.node.shell.exists.side_effect = [False, True, True]
        self.clone_run.return_value = self._result(128, stderr=self._disconnect)

        with self.assertRaisesRegex(LisaException, "failed to clean") as raised:
            self.git.clone(
                "https://example.com/netperf",
                self._cwd,
                dir_name="netperf",
                max_attempts=3,
            )

        self.assertIn("fatal: early EOF", str(raised.exception))
        self.assertIn("partial clone still exists", str(raised.exception.__cause__))
        self.clone_run.assert_called_once()
        self.sleep.assert_not_called()

    def test_retries_require_explicit_direct_child(self) -> None:
        for dir_name in (
            "",
            ".",
            "..",
            "../netperf",
            "/other/netperf",
            "child/netperf",
        ):
            with self.subTest(dir_name=dir_name):
                with self.assertRaisesRegex(LisaException, "direct child"):
                    self.git.clone(
                        "https://example.com/netperf",
                        self._cwd,
                        dir_name=dir_name,
                        max_attempts=3,
                    )

                self.clone_run.assert_not_called()
                self.node.shell.exists.assert_not_called()
                self.node.shell.remove.assert_not_called()
