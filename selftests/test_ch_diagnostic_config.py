# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import inspect
import json
import os
import runpy
import shlex
from pathlib import Path, PurePath, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Dict, List, Optional, Tuple
from unittest import TestCase
from unittest.mock import MagicMock, patch

import toml

from lisa.executable import ExecutableResult
from lisa.microsoft.testsuites.cloud_hypervisor.ch_diagnostic_config import (
    CARGO_CONFIG_PROBE,
    create_cargo_config,
    create_nextest_config,
    diagnostic_volume,
)
from lisa.microsoft.testsuites.cloud_hypervisor.ch_tests import CloudHypervisorTestSuite
from lisa.microsoft.testsuites.cloud_hypervisor.ch_tests_tool import (
    CloudHypervisorTests,
)
from lisa.tools.grep import Grep
from lisa.util import LisaException

CARGO_CONFIG = """
[profile.release]
opt-level = "s"
lto = true
codegen-units = 1
strip = true

[env]
KEEP_ME = "unchanged"
RUST_BACKTRACE = { value = "0", relative = true }

[registries.private]
token = "private-registry-value"
"""

NEXTEST_CONFIG = """
[profile.default]
slow-timeout = { period = "60s", terminate-after = 10 }

[profile.integration]
fail-fast = false
retries = 3

[profile.common_tests]
inherits = "integration"
default-filter = 'test(common_parallel::) | test(common_sequential::)'
junit.path = "/root/workloads/junit/common.xml"
junit.store-success-output = false

[[profile.common_tests.overrides]]
filter = 'test(common_sequential::)'
threads-required = 'num-test-threads'
junit = { store-success-output = false, store-failure-output = false }

[profile.common_cvm]
inherits = "integration"
junit.path = "/root/workloads/junit/cvm.xml"
"""


class DiagnosticConfigTestCase(TestCase):
    def test_cargo_changes_only_diagnostic_settings(self) -> None:
        original = toml.loads(CARGO_CONFIG)
        updated = toml.loads(create_cargo_config(CARGO_CONFIG))
        original["profile"]["release"].update(debug=2, strip="none")
        original["env"].update(
            RUST_BACKTRACE={"value": "full", "force": True},
            RUST_LIB_BACKTRACE={"value": "1", "force": True},
        )
        self.assertEqual(original, updated)

    def test_empty_cargo_config_is_supported(self) -> None:
        config = toml.loads(create_cargo_config(""))
        self.assertEqual({"debug": 2, "strip": "none"}, config["profile"]["release"])

    def test_nextest_retains_output_without_changing_test_settings(self) -> None:
        original = toml.loads(NEXTEST_CONFIG)
        updated = toml.loads(create_nextest_config(NEXTEST_CONFIG))
        for profile in original["profile"].values():
            profile.setdefault("junit", {}).update(
                {"store-success-output": True, "store-failure-output": True}
            )
            for override in profile.get("overrides", []):
                override.setdefault("junit", {}).update(
                    {"store-success-output": True, "store-failure-output": True}
                )
        self.assertEqual(original, updated)

    def test_malformed_toml_does_not_disclose_config_values(self) -> None:
        for factory in (create_cargo_config, create_nextest_config):
            with self.subTest(factory=factory.__name__):
                with self.assertRaises(LisaException) as raised:
                    factory('secret = "private-registry-value')
                self.assertIn("Invalid", str(raised.exception))
                self.assertNotIn("private-registry-value", str(raised.exception))
                self.assertTrue(raised.exception.__suppress_context__)

    def test_cargo_rejects_invalid_tables(self) -> None:
        for content in ("profile = 3", "[profile]\nrelease = false", 'env = "bad"'):
            with self.subTest(content=content):
                with self.assertRaisesRegex(LisaException, "TOML table"):
                    create_cargo_config(content)

    def test_nextest_requires_profiles_and_report_paths(self) -> None:
        for content in (
            "",
            "[profile.integration]\nretries = 3",
            "[profile.common_tests]\njunit.path = false",
            "[profile.common_tests]\njunit.path = ''",
        ):
            with self.subTest(content=content):
                with self.assertRaises(LisaException):
                    create_nextest_config(content)

    def test_nextest_rejects_invalid_overrides(self) -> None:
        for value in ('"bad"', "[1]"):
            content = (
                "[profile.common_tests]\n"
                f"overrides = {value}\n"
                'junit.path = "/root/workloads/junit/common.xml"'
            )
            with self.subTest(value=value):
                with self.assertRaises(LisaException):
                    create_nextest_config(content)

    def test_mounts_are_read_only_unless_preparing(self) -> None:
        source = PurePosixPath("/work/input.toml")
        target = PurePosixPath("/usr/local/rust/config.toml")
        self.assertEqual(
            "/work/input.toml:/usr/local/rust/config.toml:ro",
            diagnostic_volume(source, target),
        )
        self.assertTrue(
            diagnostic_volume(source, target, read_only=False).endswith(":rw")
        )

    def test_unsafe_mount_paths_fail_explicitly(self) -> None:
        for value in (
            "relative",
            "/has space",
            "/has:colon",
            "/has#separator",
            "/has$dollar",
            "/has*glob",
            "/has\nnewline",
        ):
            for source, target in (
                (PurePosixPath(value), PurePosixPath("/safe")),
                (PurePosixPath("/safe"), PurePosixPath(value)),
            ):
                with self.subTest(source=source, target=target):
                    with self.assertRaisesRegex(LisaException, "unsupported"):
                        diagnostic_volume(source, target)


class CargoConfigProbeTestCase(TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.workspace = self.root / "repo"
        self.workspace.mkdir()
        self.home = self.root / "cargo-home"
        self.home.mkdir()
        self.output = self.root / "output"
        self.output.mkdir()

    def _probe(
        self, cargo_home: str = "", overrides: Optional[Dict[str, str]] = None
    ) -> Tuple[str, str]:
        script = self.root / "probe.py"
        script.write_text(CARGO_CONFIG_PROBE, encoding="utf-8")
        original_exists = Path.exists

        def exists(path: Path) -> bool:
            # Do not inspect real user/ancestor Cargo configuration in this test.
            return self.root in path.parents and original_exists(path)

        environment = {"CARGO_HOME": cargo_home or str(self.home)}
        environment.update(overrides or {})
        with patch.dict(os.environ, environment, clear=True), patch(
            "os.getcwd", return_value=str(self.workspace)
        ), patch.object(Path, "exists", exists), patch(
            "sys.argv", ["probe", str(self.output)]
        ):
            runpy.run_path(str(script), run_name="__main__")

        target = json.loads(
            (self.output / "cargo-config-path.json").read_text(encoding="utf-8")
        )
        self.assertIsInstance(target, str)
        return str(target), (self.output / "cargo-original.toml").read_text(
            encoding="utf-8"
        )

    def test_missing_configuration_uses_cargo_home(self) -> None:
        target, original = self._probe()
        self.assertEqual(str(self.home / "config.toml"), target)
        self.assertEqual("", original)

    def test_legacy_config_takes_precedence(self) -> None:
        (self.home / "config").write_text(CARGO_CONFIG, encoding="utf-8")
        (self.home / "config.toml").write_text("other = true", encoding="utf-8")
        target, original = self._probe()
        self.assertEqual(str(self.home / "config"), target)
        self.assertEqual(CARGO_CONFIG, original)

    def test_workspace_config_takes_precedence_and_is_not_modified(self) -> None:
        (self.home / "config.toml").write_text("other = true", encoding="utf-8")
        config = self.workspace / ".cargo" / "config.toml"
        config.parent.mkdir()
        config.write_text(CARGO_CONFIG, encoding="utf-8")
        target, original = self._probe()
        self.assertEqual(str(config), target)
        self.assertEqual(CARGO_CONFIG, original)
        self.assertEqual(CARGO_CONFIG, config.read_text(encoding="utf-8"))

    def test_relative_cargo_home_is_resolved_from_container_workdir(self) -> None:
        target, _ = self._probe("relative-home")
        self.assertEqual(str(self.workspace / "relative-home" / "config.toml"), target)

    def test_ancestor_config_takes_precedence_over_cargo_home(self) -> None:
        config = self.root / ".cargo" / "config.toml"
        config.parent.mkdir()
        config.write_text(CARGO_CONFIG, encoding="utf-8")
        (self.home / "config.toml").write_text("other = true", encoding="utf-8")
        target, original = self._probe()
        self.assertEqual(str(config), target)
        self.assertEqual(CARGO_CONFIG, original)

    def test_conflicting_cargo_profile_environment_is_rejected(self) -> None:
        for key, value in (
            ("CARGO_PROFILE_RELEASE_DEBUG", "0"),
            ("CARGO_PROFILE_RELEASE_STRIP", "symbols"),
        ):
            with self.subTest(key=key):
                with self.assertRaisesRegex(RuntimeError, key):
                    self._probe(overrides={key: value})


class DiagnosticIntegrationTestCase(TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.log_path = Path(self.directory.name)
        self.node = MagicMock()
        self.result = ExecutableResult(
            _stdout="container preparation output",
            _stderr="container preparation stderr",
            exit_code=0,
            cmd="test command",
            _id_="test",
            elapsed=0,
        )
        self.node.execute.return_value = self.result
        self.node.shell.copy_back.side_effect = self._copy_back
        self.node.shell.copy.side_effect = self._copy
        self.tool = CloudHypervisorTests.__new__(CloudHypervisorTests)
        self.tool.node = self.node
        self.tool.repo_root = PurePosixPath("/repo")
        self.log = MagicMock()
        self.tool._log = self.log
        self.tool.perf_stable_enabled = False
        self.probe = MagicMock(return_value=self.result)
        self.tool_path = MagicMock(return_value=PurePosixPath("/work"))
        self.cargo_input = CARGO_CONFIG
        self.nextest_input = NEXTEST_CONFIG
        self.target_json = json.dumps("/usr/local/rust/config.toml")
        self.provenance_input = json.dumps(
            {"status": "collected", "files": [], "errors": []}
        )
        self.copied: Dict[str, str] = {}
        self.private_paths: List[Path] = []
        for name, mock in (("run", self.probe), ("get_tool_path", self.tool_path)):
            patcher = patch.object(self.tool, name, mock)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in (
            "_setup_disk_for_metrics",
            "_ensure_host_setup",
            "_copy_back_artifacts",
            "_configure_environment_if_needed",
            "_process_test_results",
            "_save_kernel_logs",
            "_send_metrics_test_result",
            "_check_test_panic_from_logs",
        ):
            patcher = patch.object(self.tool, name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _copy_back(self, remote: PurePath, local: Path) -> None:
        inputs = {
            "cargo-original.toml": self.cargo_input,
            "cargo-config-path.json": self.target_json,
            "nextest.toml": self.nextest_input,
            "guest-provenance.json": self.provenance_input,
            "lisa_metrics_report.json": json.dumps(
                {"results": [{"name": "block_read_MiBps", "status": "PASSED"}]}
            ),
        }
        local.write_text(inputs[remote.name], encoding="utf-8")
        if remote.name != "lisa_metrics_report.json":
            self.private_paths.append(local)

    def _copy(self, local: Path, remote: PurePath) -> None:
        self.copied[remote.name] = local.read_text(encoding="utf-8")
        self.private_paths.append(local)

    def test_disabled_mode_performs_no_preparation(self) -> None:
        with self.tool._diagnostic_config(
            self.log_path, "integration", False, nextest=True
        ) as volumes:
            self.assertEqual("", volumes)
        self.probe.assert_not_called()
        self.tool_path.assert_not_called()
        self.node.execute.assert_not_called()
        self.node.shell.mkdir.assert_not_called()
        self.assertEqual([], list(self.log_path.iterdir()))

    def test_enabled_mode_merges_mounts_and_keeps_configs_private(self) -> None:
        with self.tool._diagnostic_config(
            self.log_path, "integration", True, nextest=True
        ) as volumes:
            mounts = volumes.split("#")
            self.assertEqual(2, len(mounts))
            self.assertTrue(all(mount.endswith(":ro") for mount in mounts))
            self.assertIn(":/usr/local/rust/config.toml:ro", volumes)
            self.assertIn(":/cloud-hypervisor/.config/nextest.toml:ro", volumes)
            self.assertIn("private-registry-value", self.copied["cargo.toml"])
            self.assertTrue(all(path.exists() for path in self.private_paths))

        self.node.shell.mkdir.assert_called_once()
        self.assertEqual(0o700, self.node.shell.mkdir.call_args.kwargs["mode"])
        self.assertTrue(all(not path.exists() for path in self.private_paths))
        for path in self.log_path.rglob("*"):
            if path.is_file():
                self.assertNotIn(
                    "private-registry-value", path.read_text(encoding="utf-8")
                )
        self.assertEqual(1, len(list(self.log_path.rglob("settings.json"))))
        cleanup = self.node.execute.call_args.args[0]
        self.assertIn("rm -f -- ", cleanup)
        self.assertIn("&& rmdir -- ", cleanup)
        self.assertNotIn("rm -rf", cleanup)

    def test_probe_preserves_both_layers_of_shell_quoting(self) -> None:
        with self.tool._diagnostic_config(
            self.log_path, "metrics", True, nextest=False
        ):
            pass
        args = shlex.split(self.probe.call_args_list[0].args[0])
        self.assertEqual(["shell", "--volumes"], args[:2])
        command = args[args.index("--") + 1 :]
        self.assertEqual(1, len(command))
        inner = shlex.split(command[0])
        self.assertEqual(["python3", "-c", CARGO_CONFIG_PROBE], inner[:3])
        self.assertEqual("/lisa-ch-diagnostics", inner[3])
        args = shlex.split(self.probe.call_args_list[1].args[0])
        inner = shlex.split(args[args.index("--") + 1])
        self.assertEqual("/lisa-ch-diagnostics/guest-provenance.json", inner[3])
        self.assertEqual(120, self.probe.call_args_list[1].kwargs["timeout"])

    def test_metrics_does_not_require_nextest_configuration(self) -> None:
        with self.tool._diagnostic_config(
            self.log_path, "metrics", True, nextest=False
        ) as volumes:
            self.assertNotIn("#", volumes)
        self.assertEqual({"cargo.toml"}, set(self.copied))

    def test_existing_workspace_cargo_target_is_preserved(self) -> None:
        self.target_json = json.dumps("/cloud-hypervisor/.cargo/config")
        with self.tool._diagnostic_config(
            self.log_path, "integration", True, nextest=True
        ) as volumes:
            self.assertIn(":/cloud-hypervisor/.cargo/config:ro", volumes)

    def test_failed_probe_retains_stderr_and_cleans_up(self) -> None:
        self.result.exit_code = 1
        with self.assertRaises(LisaException):
            with self.tool._diagnostic_config(
                self.log_path, "integration", True, nextest=True
            ):
                self.fail("A failed probe must not run tests")
        preparation = next(self.log_path.rglob("preparation.log"))
        content = preparation.read_text(encoding="utf-8")
        self.assertIn("exit_code=1", content)
        self.assertIn("container preparation stderr", content)
        self.node.execute.assert_called_once()
        self.node.shell.copy.assert_not_called()

    def test_probe_timeout_is_not_treated_as_success(self) -> None:
        self.result.is_timeout = True
        with self.assertRaisesRegex(LisaException, "timed out"):
            with self.tool._diagnostic_config(
                self.log_path, "integration", True, nextest=True
            ):
                self.fail("A timed-out probe must not run tests")
        self.node.execute.assert_called_once()

    def test_invalid_configuration_cleans_up_and_does_not_fall_back(self) -> None:
        self.cargo_input = "env = 1"
        with self.assertRaisesRegex(LisaException, "TOML table"):
            with self.tool._diagnostic_config(
                self.log_path, "integration", True, nextest=True
            ):
                self.fail("Invalid configuration must not run tests")
        self.assertTrue(all(not path.exists() for path in self.private_paths))
        self.node.execute.assert_called_once()

    def test_invalid_probe_path_fails_explicitly(self) -> None:
        for value in ("42", json.dumps("/path with spaces/config.toml")):
            with self.subTest(value=value):
                self.target_json = value
                with self.assertRaises(LisaException):
                    with self.tool._diagnostic_config(
                        self.log_path, "metrics", True, nextest=False
                    ):
                        self.fail("Invalid mount target must not run tests")

    def test_cleanup_failure_does_not_replace_runner_failure(self) -> None:
        self.node.execute.side_effect = OSError("cleanup unavailable")
        with self.assertRaisesRegex(LisaException, "runner failure"):
            with self.tool._diagnostic_config(
                self.log_path, "metrics", True, nextest=False
            ):
                raise LisaException("runner failure")
        self.log.warning.assert_called_once()
        self.assertTrue(all(not path.exists() for path in self.private_paths))

    def test_nonzero_cleanup_does_not_replace_runner_failure(self) -> None:
        self.node.execute.return_value = ExecutableResult(
            _stdout="",
            _stderr="permission denied",
            exit_code=1,
            cmd="cleanup",
            _id_="cleanup",
            elapsed=0,
        )
        with self.assertRaisesRegex(LisaException, "runner failure"):
            with self.tool._diagnostic_config(
                self.log_path, "metrics", True, nextest=False
            ):
                raise LisaException("runner failure")
        self.log.warning.assert_called_once()
        self.assertIn("permission denied", self.log.warning.call_args.args[0])

    def test_each_invocation_has_separate_configuration(self) -> None:
        mounts = []
        for _ in range(2):
            with self.tool._diagnostic_config(
                self.log_path, "metrics", True, nextest=False
            ) as volumes:
                mounts.append(volumes)
        self.assertNotEqual(mounts[0], mounts[1])
        self.assertEqual(2, len(list(self.log_path.rglob("settings.json"))))

    def test_integration_passes_mounts_to_discovery_and_runner(self) -> None:
        with patch.object(
            self.tool,
            "_prepare_subtests",
            return_value={"skip_args": "", "subtest_set": {"test"}},
        ) as prepare, patch.object(
            self.tool, "_run_with_enhanced_diagnostics", return_value=self.result
        ) as runner:
            self.tool.run_tests(
                MagicMock(),
                "integration",
                "mshv",
                self.log_path,
                capture_diagnostics=True,
            )
        volumes = prepare.call_args.args[-1]
        self.assertTrue(volumes)
        args = shlex.split(runner.call_args.kwargs["cmd_args"])
        self.assertEqual(volumes, args[args.index("--volumes") + 1])
        self.assertLess(args.index("--volumes"), args.index("--"))

    def test_cvm_and_filtered_discovery_receive_mounts(self) -> None:
        with patch.object(
            self.tool,
            "_prepare_filtered_subtests",
            return_value={"skip_args": "", "subtest_set": {"common_cvm::test"}},
        ) as prepare, patch.object(
            self.tool, "_run_with_enhanced_diagnostics", return_value=self.result
        ) as runner:
            self.tool.run_tests(
                MagicMock(),
                "integration-cvm",
                "mshv",
                self.log_path,
                cli_test_filter="common_cvm",
                capture_diagnostics=True,
            )
        self.assertTrue(prepare.call_args.args[-1])
        args = shlex.split(runner.call_args.kwargs["cmd_args"])
        self.assertIn("--integration-cvm", args)
        self.assertLess(args.index("--volumes"), args.index("--test-filter"))

    def test_runner_exception_collects_junit_without_masking_error(self) -> None:
        with patch.object(
            self.tool,
            "_prepare_subtests",
            return_value={"skip_args": "", "subtest_set": set()},
        ), patch.object(
            self.tool,
            "_run_with_enhanced_diagnostics",
            side_effect=LisaException("runner failure"),
        ), patch.object(
            self.tool,
            "_collect_nextest_junit_files",
            side_effect=OSError("collection unavailable"),
        ) as collect:
            with self.assertRaisesRegex(LisaException, "runner failure"):
                self.tool.run_tests(
                    MagicMock(),
                    "integration",
                    "kvm",
                    self.log_path,
                    capture_diagnostics=True,
                )
        collect.assert_called_once_with(self.log_path)
        self.log.warning.assert_called_once()
        self.assertTrue(all(not path.exists() for path in self.private_paths))

    def test_metrics_success_uses_mounts_and_preserves_report(self) -> None:
        with patch.object(
            self.tool, "_run_with_enhanced_diagnostics", return_value=self.result
        ) as runner:
            self.tool.run_metrics_tests(
                MagicMock(),
                "kvm",
                self.log_path,
                only="block qcow2",
                capture_diagnostics=True,
            )
        args = shlex.split(runner.call_args.kwargs["cmd_args"])
        self.assertLess(args.index("--volumes"), args.index("--"))
        self.assertEqual("block qcow2", args[args.index("--test-filter") + 1])
        self.assertTrue((self.log_path / "lisa_metrics_report.json").exists())

    def test_metrics_exception_preserves_existing_artifact_collection(self) -> None:
        with patch.object(
            self.tool,
            "_run_with_enhanced_diagnostics",
            side_effect=LisaException("runner failure"),
        ), patch.object(self.tool, "_copy_back_artifacts") as collect:
            with self.assertRaisesRegex(LisaException, "runner failure"):
                self.tool.run_metrics_tests(
                    MagicMock(),
                    "kvm",
                    self.log_path,
                    capture_diagnostics=True,
                )
        collect.assert_called_once_with(self.log_path, "ch_metrics_all_kvm")
        self.assertTrue(all(not path.exists() for path in self.private_paths))

    def test_default_metrics_command_is_unchanged(self) -> None:
        with patch.object(
            self.tool,
            "_run_with_enhanced_diagnostics",
            side_effect=LisaException("runner failure"),
        ) as runner:
            with self.assertRaisesRegex(LisaException, "runner failure"):
                self.tool.run_metrics_tests(MagicMock(), "kvm", self.log_path)
        self.probe.assert_not_called()
        self.assertEqual(
            "tests --hypervisor kvm --metrics -- -- --continue-on-failure"
            " --report-file /cloud-hypervisor/lisa_metrics_report.json",
            runner.call_args.kwargs["cmd_args"],
        )

    def test_guest_provenance_error_does_not_replace_runner_error(self) -> None:
        with self.assertRaisesRegex(LisaException, "runner failure"):
            with self.tool._diagnostic_config(
                self.log_path, "metrics", True, nextest=False
            ):
                self.probe.return_value = ExecutableResult(
                    _stdout="probe stdout",
                    _stderr="probe permission denied",
                    exit_code=1,
                    cmd="probe",
                    _id_="probe",
                    elapsed=0,
                )
                raise LisaException("runner failure")
        report = json.loads(
            next(self.log_path.rglob("guest_identity.json")).read_text(encoding="utf-8")
        )
        self.assertEqual("unavailable", report["configured_provenance"]["status"])
        self.assertIsNone(report["runtime_identity"]["kernel_version"])
        probe_log = next(self.log_path.rglob("guest_provenance.log")).read_text(
            encoding="utf-8"
        )
        self.assertIn("probe stdout", probe_log)
        self.assertIn("probe permission denied", probe_log)
        self.log.warning.assert_called_once()
        self.assertTrue(all(not path.exists() for path in self.private_paths))

    def test_guest_provenance_rejects_invalid_reports(self) -> None:
        for invalid in ('{"errors": []}', "[]", "not json"):
            with self.subTest(invalid=invalid):
                self.provenance_input = invalid
                with self.tool._diagnostic_config(
                    self.log_path, "metrics", True, nextest=False
                ):
                    pass
        reports = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in self.log_path.rglob("guest_identity.json")
        ]
        self.assertEqual(3, len(reports))
        self.assertTrue(
            all(
                report["configured_provenance"]["status"] == "unavailable"
                for report in reports
            )
        )
        self.assertEqual(3, self.log.warning.call_count)

    def test_guest_provenance_keeps_selected_inputs_separate_from_runtime(self) -> None:
        self.tool._custom_kernel_metadata = {
            "path": "/usr/share/cloud-hypervisor/vmlinux.bin",
            "embedded-build": "6.12.0-custom (builder)",
            "collected_at_utc": "2026-01-01T00:00:00+00:00",
        }
        with patch.dict(
            self.tool.env_vars,
            {
                "CH_CUSTOM_KERNEL": "/usr/share/cloud-hypervisor/vmlinux.bin",
                "AUTH_DOWNLOAD_TOKEN": "do-not-publish",
            },
        ), self.tool._diagnostic_config(self.log_path, "metrics", True, nextest=False):
            (self.log_path / "metrics.log").write_text(
                "==== Start child stdout ====\n"
                "Welcome to Ubuntu 22.04.5 LTS!\n"
                "==== End child stdout ====\n",
                encoding="utf-8",
            )
        content = next(self.log_path.rglob("guest_identity.json")).read_text(
            encoding="utf-8"
        )
        self.assertNotIn("do-not-publish", content)
        report = json.loads(content)
        self.assertEqual("observations_only", report["console_evidence_status"])
        self.assertEqual(
            "6.12.0-custom (builder)",
            report["configured_provenance"]["selected_custom_kernel_metadata"][
                "embedded-build"
            ],
        )
        self.assertIsNone(report["runtime_identity"]["kernel_version"])
        self.assertIsNone(report["runtime_identity"]["distro"])

    def test_selected_kernel_metadata_cache_preserves_existing_log(self) -> None:
        self.node.get_pure_path.side_effect = PurePosixPath

        def result(stdout: str) -> ExecutableResult:
            return ExecutableResult(
                _stdout=stdout,
                _stderr="",
                exit_code=0,
                cmd="kernel metadata",
                _id_="metadata",
                elapsed=0,
            )

        self.node.execute.side_effect = [
            result(""),
            result(f"{'a' * 64}  /guest/vmlinux"),
            result("ELF guest kernel"),
        ]
        self.node.tools[Grep].run.return_value = result(
            "Linux version 6.12-custom (guest-builder)"
        )
        module = "lisa.microsoft.testsuites.cloud_hypervisor.ch_tests_tool"
        with patch(f"{module}.Rpm") as rpm, patch(f"{module}.Dpkg") as dpkg:
            rpm.return_value.exists = False
            dpkg.return_value.exists = False
            self.tool._log_custom_kernel_metadata("/guest/vmlinux")
        metadata = self.tool._custom_kernel_metadata
        assert metadata is not None
        self.assertEqual("/guest/vmlinux", metadata["path"])
        self.assertEqual("a" * 64, metadata["sha256"])
        self.assertEqual(
            "Linux version 6.12-custom (guest-builder)", metadata["embedded-build"]
        )
        self.assertIn("collected_at_utc", metadata)
        self.log.info.assert_called_once_with(
            "Selected UVM kernel metadata:\n"
            "[uvm-kernel] path=/guest/vmlinux\n"
            "[uvm-kernel] embedded-build=Linux version 6.12-custom (guest-builder)\n"
            f"[uvm-kernel] sha256={'a' * 64}\n"
            "[uvm-kernel] file=ELF guest kernel"
        )

    def test_nextest_listing_receives_mounts_before_separator(self) -> None:
        with patch.object(
            self.tool, "_parse_nextest_subtest_list", return_value=["common_cvm::test"]
        ):
            self.tool._list_subtests("mshv", "integration-cvm", "/input:/target:ro")
        args = shlex.split(self.probe.call_args.args[0])
        self.assertEqual(["shell", "--volumes", "/input:/target:ro", "--"], args[:4])
        self.assertIn("common_cvm", args)

    def test_default_integration_commands_are_unchanged(self) -> None:
        self.assertEqual(
            "tests --hypervisor kvm --integration -- -- ",
            self.tool._build_tests_command("integration", "kvm"),
        )
        self.assertEqual(
            "tests --integration-cvm --hypervisor mshv",
            self.tool._build_tests_command("integration-cvm", "mshv"),
        )

    def test_watchdog_no_longer_contains_the_sampler(self) -> None:
        self.tool._run_with_enhanced_diagnostics("tests --metrics", timeout=10)
        script = shlex.split(self.node.execute.call_args.args[0])[2]
        self.assertNotIn("ch_diag_snapshot", script)
        self.assertNotIn("diagnostics_file", script)
        self.assertIn('2>&1 | tee -a "$log_file"', script)
        self.assertIn("exit $ec", script)

    def test_suite_keeps_the_case_visible_opt_in_for_all_entry_points(self) -> None:
        suite_type = inspect.unwrap(CloudHypervisorTestSuite)
        suite = object.__new__(suite_type)
        entry_points = (
            ("verify_cloud_hypervisor_performance_metrics_tests", "run_metrics_tests"),
            ("verify_cloud_hypervisor_integration_tests", "run_tests"),
            ("verify_cloud_hypervisor_live_migration_tests", "run_tests"),
        )
        with patch.object(suite, "_get_hypervisor_param", return_value="kvm"):
            for entry, runner in entry_points:
                for value, expected in (("true", True), ("false", False), (True, True)):
                    with self.subTest(entry=entry, value=value):
                        getattr(suite, entry)(
                            self.node,
                            self.log_path,
                            MagicMock(),
                            {"ch_capture_diagnostics": value},
                        )
                        call = getattr(
                            self.node.tools.__getitem__.return_value, runner
                        ).call_args
                        self.assertIs(expected, call.kwargs["capture_diagnostics"])
