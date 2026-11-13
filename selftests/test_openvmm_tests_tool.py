# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.microsoft.testsuites.openvmm.openvmm_artifacts import CONFIGURATIONS
from lisa.microsoft.testsuites.openvmm.openvmm_tests_tool import OpenVmmTests
from lisa.tools import Curl
from lisa.util import LisaException


class OpenVmmTestsToolTestCase(TestCase):
    def test_set_repo_paths_uses_repo_url_hash(self) -> None:
        tool = OpenVmmTests.__new__(OpenVmmTests)

        with patch.object(tool, "get_tool_path", return_value=PurePosixPath("/tools")):
            tool.repo_url = "https://example.com/first/openvmm.git"
            tool._set_repo_paths()
            first_repo_root = tool.repo_root

            tool.repo_url = "https://example.com/second/openvmm.git"
            tool._set_repo_paths()

        self.assertNotEqual(first_repo_root, tool.repo_root)
        self.assertTrue(str(first_repo_root).startswith("/tools/openvmm-"))
        self.assertTrue(str(tool.repo_root).startswith("/tools/openvmm-"))

    def test_run_logged_command_redirects_entire_command_to_log(self) -> None:
        tool = OpenVmmTests.__new__(OpenVmmTests)
        tool.repo_root = PurePosixPath("/repo/openvmm")
        tool._artifact_root = PurePosixPath("/repo/openvmm/target/lisa-openvmm-tests")
        tool.node = MagicMock()
        tool.node.execute.return_value = SimpleNamespace(exit_code=0)
        with TemporaryDirectory() as temp_dir, patch.object(
            tool, "_copy_back_if_exists"
        ):
            tool._run_logged_command(
                name="openvmm_sample",
                command="echo before && false",
                log_path=Path(temp_dir),
                timeout=60,
                update_envs={},
            )

        logged_command = tool.node.execute.call_args.args[0]
        self.assertIn(
            "{ echo before && false; } > "
            "/repo/openvmm/target/lisa-openvmm-tests/openvmm_sample.log 2>&1",
            logged_command,
        )

    def test_ensure_cargo_nextest_uses_release_checksum_asset(self) -> None:
        tool = OpenVmmTests.__new__(OpenVmmTests)
        tool._artifact_root = PurePosixPath("/repo/openvmm/target/lisa-openvmm-tests")
        tool.node = MagicMock()
        tool.node.tools = {Curl: SimpleNamespace(command="curl")}
        tool._log = MagicMock()
        with TemporaryDirectory() as temp_dir, patch.object(
            tool, "_has_cargo_nextest", side_effect=[False, True]
        ), patch.object(
            tool, "_get_nextest_version", return_value="0.9.101"
        ), patch.object(
            tool, "_run_logged_command"
        ) as run_logged_command:
            tool._ensure_cargo_nextest(Path(temp_dir), {})

        install_command = run_logged_command.call_args.kwargs["command"]
        release_url = (
            "https://github.com/nextest-rs/nextest/releases/download/"
            "cargo-nextest-0.9.101"
        )
        asset_name = "cargo-nextest-0.9.101-x86_64-unknown-linux-gnu"
        self.assertIn(f"{release_url}/{asset_name}.tar.gz", install_command)
        self.assertIn(f"{release_url}/{asset_name}.sha256", install_command)

    def test_native_prerequisite_checks_use_selected_device_group(self) -> None:
        tool = OpenVmmTests.__new__(OpenVmmTests)
        tool.node = MagicMock()
        tool.node.execute.return_value = SimpleNamespace(exit_code=0, stdout="")
        tool.command_group = "kvm"
        with TemporaryDirectory() as temp_dir, patch.object(
            tool, "_ensure_cargo_nextest"
        ), patch.object(tool, "_run_logged_command"):
            with tool._prepare_native_execution(
                CONFIGURATIONS[1],
                PurePosixPath("/content"),
                {},
                Path(temp_dir),
                install_missing_deps=False,
            ):
                pass

        commands = [call.args[0] for call in tool.node.execute.call_args_list]
        prerequisite_check = commands[-1]
        self.assertIn("sg kvm -c", prerequisite_check)
        self.assertIn("/dev/kvm", prerequisite_check)
        self.assertIn("/dev/vhost-vsock", prerequisite_check)
        self.assertNotIn("chmod a+rw", " ".join(commands))

    def test_native_kvm_setup_restores_hugepage_limit(self) -> None:
        tool = OpenVmmTests.__new__(OpenVmmTests)
        tool.node = MagicMock()
        tool.node.execute.side_effect = [
            SimpleNamespace(exit_code=0, stdout=""),
            SimpleNamespace(exit_code=0, stdout="17"),
            SimpleNamespace(exit_code=0, stdout=""),
            SimpleNamespace(exit_code=0, stdout=""),
            SimpleNamespace(exit_code=0, stdout=""),
            SimpleNamespace(exit_code=0, stdout=""),
        ]
        tool.command_group = "kvm"
        with TemporaryDirectory() as temp_dir, patch.object(
            tool, "_ensure_cargo_nextest"
        ), patch.object(tool, "_run_logged_command"):
            with tool._prepare_native_execution(
                CONFIGURATIONS[1],
                PurePosixPath("/content"),
                {},
                Path(temp_dir),
                install_missing_deps=True,
            ):
                pass

        commands = [call.args[0] for call in tool.node.execute.call_args_list]
        self.assertIn("echo 4096", commands[2])
        self.assertIn("sg kvm -c", commands[3])
        self.assertIn("echo 17 >", commands[-1])
        tool.node.mark_dirty.assert_called_once_with()

    def test_native_setup_restores_temporary_vsock_acl(self) -> None:
        tool = OpenVmmTests.__new__(OpenVmmTests)
        tool.node = MagicMock()
        commands = []

        def execute(command: str, **kwargs: object) -> SimpleNamespace:
            commands.append(command)
            if command.startswith("getfacl"):
                return SimpleNamespace(
                    exit_code=0,
                    stdout="user::rw-\ngroup::rw-\nother::---\n",
                )
            if command == "id -un":
                return SimpleNamespace(exit_code=0, stdout="runner\n")
            if command.startswith("sg mshv -c 'test -r /dev/vhost-vsock"):
                return SimpleNamespace(exit_code=1, stdout="")
            return SimpleNamespace(exit_code=0, stdout="")

        tool.node.execute.side_effect = execute
        tool.command_group = "mshv"
        with TemporaryDirectory() as temp_dir, patch.object(
            tool, "_ensure_cargo_nextest"
        ), patch.object(tool, "_run_logged_command"):
            with tool._prepare_native_execution(
                CONFIGURATIONS[0],
                PurePosixPath("/content"),
                {},
                Path(temp_dir),
                install_missing_deps=True,
            ):
                pass

        self.assertTrue(any("setfacl -m u:runner:rw " in cmd for cmd in commands))
        restore = next(cmd for cmd in commands if "setfacl --set-file=-" in cmd)
        self.assertIn("user::rw-", restore)
        self.assertIn(
            "sg mshv -c", next(cmd for cmd in commands if "vhost-vsock" in cmd)
        )
        self.assertNotIn("chmod a+rw", " ".join(commands))
        tool.node.mark_dirty.assert_called_once_with()

    def test_check_vmm_tests_results_raises_on_junit_failures(self) -> None:
        tool = OpenVmmTests.__new__(OpenVmmTests)

        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            log_file = temp_path / "openvmm_vmm_tests.log"
            junit_file = temp_path / "openvmm_vmm_tests.junit.xml"
            log_file.write_text("", encoding="utf-8")
            junit_file.write_text(
                """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="x64-linux-vmm-tests" tests="48" failures="7" errors="0" skipped="41">
    <testcase
      classname="vmm_tests::tests"
      name="multiarch::ic::openvmm_uefi_x64_ubuntu_2504_server_x64_timesync_ic">
      <failure message="failed">stack</failure>
    </testcase>
  </testsuite>
</testsuites>
""",
                encoding="utf-8",
            )

            with self.assertRaises(LisaException) as context:
                tool._check_vmm_tests_results(
                    name="openvmm_vmm_tests",
                    log_file=log_file,
                    junit_file=junit_file,
                )

            self.assertIn(
                "7 tests run: 0 passed, 7 failed, 41 skipped",
                str(context.exception),
            )
            self.assertIn("Failed tests:", str(context.exception))
        self.assertIn(
            "multiarch::ic::openvmm_uefi_x64_ubuntu_2504_server_x64_timesync_ic",
            str(context.exception),
        )

    def test_parse_junit_rejects_failure_elements_with_zero_suite_counts(self) -> None:
        tool = OpenVmmTests.__new__(OpenVmmTests)
        with TemporaryDirectory() as temp_dir:
            junit_file = Path(temp_dir) / "inconsistent.junit.xml"
            junit_file.write_text(
                """<testsuite tests="1" failures="0" errors="0">
  <testcase classname="suite" name="failed"><failure /></testcase>
</testsuite>
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(LisaException, "failure elements"):
                tool._parse_junit_summary(junit_file)

    def test_check_vmm_tests_results_raises_on_log_summary_without_junit(self) -> None:
        tool = OpenVmmTests.__new__(OpenVmmTests)

        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            log_file = temp_path / "openvmm_vmm_tests.log"
            log_file.write_text(
                """
Summary [   0.071s] 7/17 tests run: 0 passed, 7 failed, 41 skipped
    FAIL [   0.069s] vmm_tests::tests
          multiarch::ic::openvmm_uefi_x64_ubuntu_2504_server_x64_timesync_ic
warning: 10/17 tests were not run due to test failure
error: test run failed
encountered at least one test failure!
encountered test failures.
""",
                encoding="utf-8",
            )

            with self.assertRaises(LisaException) as context:
                tool._check_vmm_tests_results(
                    name="openvmm_vmm_tests",
                    log_file=log_file,
                    junit_file=temp_path / "missing.junit.xml",
                )

            self.assertIn(
                "7/17 tests run: 0 passed, 7 failed, 41 skipped",
                str(context.exception),
            )
        self.assertIn("7 failed", str(context.exception))

    def test_check_vmm_tests_results_deduplicates_failed_tests_and_reports_passes(
        self,
    ) -> None:
        tool = OpenVmmTests.__new__(OpenVmmTests)

        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            log_file = temp_path / "openvmm_vmm_tests.log"
            log_file.write_text(
                """
Summary [ 600.338s] 3 tests run: 2 passed, 1 failed, 45 skipped
    PASS [ 120.000s] vmm_tests::tests
          multiarch::openvmm_uefi_x64_ubuntu_2404_server_x64_boot
    PASS [ 130.000s] vmm_tests::tests
          multiarch::ic::openvmm_uefi_x64_ubuntu_2504_server_x64_timesync_ic
    FAIL [ 600.335s] vmm_tests::tests
          multiarch::openvmm_uefi_x64_alpine_3_23_x64_boot_small
    FAIL [ 600.335s] vmm_tests::tests
          multiarch::openvmm_uefi_x64_alpine_3_23_x64_boot_small
encountered at least one test failure!
""",
                encoding="utf-8",
            )

            with self.assertRaises(LisaException) as context:
                tool._check_vmm_tests_results(
                    name="openvmm_vmm_tests",
                    log_file=log_file,
                    junit_file=temp_path / "missing.junit.xml",
                )

        message = str(context.exception)
        self.assertIn("3 tests run: 2 passed, 1 failed, 45 skipped", message)
        self.assertIn("Passed tests:", message)
        self.assertIn("Failed tests:", message)
        failed_test_name = "multiarch::openvmm_uefi_x64_alpine_3_23_x64_boot_small"
        self.assertEqual(
            1,
            message.count(failed_test_name),
        )

    def test_check_vmm_tests_results_accepts_passing_junit(self) -> None:
        tool = OpenVmmTests.__new__(OpenVmmTests)

        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            log_file = temp_path / "openvmm_vmm_tests.log"
            junit_file = temp_path / "openvmm_vmm_tests.junit.xml"
            log_file.write_text("", encoding="utf-8")
            junit_file.write_text(
                """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="x64-linux-vmm-tests" tests="2" failures="0" errors="0" skipped="1">
    <testcase classname="vmm_tests::tests" name="multiarch::openvmm_boot" />
    <testcase classname="vmm_tests::tests" name="multiarch::openvmm_skip">
      <skipped message="filtered" />
    </testcase>
  </testsuite>
</testsuites>
""",
                encoding="utf-8",
            )

            summary = tool._check_vmm_tests_results(
                name="openvmm_vmm_tests",
                log_file=log_file,
                junit_file=junit_file,
            )

        self.assertEqual(1, summary.tests)
        self.assertEqual(1, summary.skipped)
        self.assertEqual(
            ["vmm_tests::tests multiarch::openvmm_boot"],
            summary.passed_tests,
        )

    def test_archive_remote_directory_logs_warning_on_failure(self) -> None:
        tool = OpenVmmTests.__new__(OpenVmmTests)
        tool.node = MagicMock()
        tool._log = MagicMock()
        tool.node.execute.return_value = SimpleNamespace(
            exit_code=1, stdout="", stderr="No such file or directory"
        )

        tool._archive_remote_directory(
            source_dir=PurePosixPath("/remote/artifacts"),
            archive_path=PurePosixPath("/remote/artifacts.tar.gz"),
        )

        tool._log.warning.assert_called_once()
        warning_message = tool._log.warning.call_args.args[0]
        self.assertIn("/remote/artifacts", warning_message)
        self.assertIn("/remote/artifacts.tar.gz", warning_message)

    def test_archive_remote_directory_does_not_warn_on_success(self) -> None:
        tool = OpenVmmTests.__new__(OpenVmmTests)
        tool.node = MagicMock()
        tool._log = MagicMock()
        tool.node.execute.return_value = SimpleNamespace(
            exit_code=0, stdout="", stderr=""
        )

        tool._archive_remote_directory(
            source_dir=PurePosixPath("/remote/artifacts"),
            archive_path=PurePosixPath("/remote/artifacts.tar.gz"),
        )

        tool._log.warning.assert_not_called()
