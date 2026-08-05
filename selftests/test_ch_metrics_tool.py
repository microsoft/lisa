# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, Dict, List, cast
from unittest import TestCase
from unittest.mock import MagicMock, patch

from paramiko.ssh_exception import SSHException

from lisa.executable import ExecutableResult
from lisa.messages import TestStatus
from lisa.microsoft.testsuites.cloud_hypervisor.ch_tests_tool import (
    CloudHypervisorTests,
)
from lisa.util import LisaException

_MODULE = "lisa.microsoft.testsuites.cloud_hypervisor.ch_tests_tool"


def _result(stdout: str) -> ExecutableResult:
    return cast(ExecutableResult, SimpleNamespace(stdout=stdout, exit_code=0))


def _run_result(exit_code: int = 0) -> ExecutableResult:
    # Minimal stand-in for the ExecutableResult returned by the retry run.
    return cast(ExecutableResult, SimpleNamespace(stdout="", exit_code=exit_code))


# Realistic excerpt of the Cloud Hypervisor performance-metrics stdout showing
# the structured markers emitted when a subtest is killed on the harness'
# own wall-clock timeout (as opposed to a functional failure).
_TIMEOUT_STDOUT = (
    "Test 'block_read_MiBps' .. ok: mean = 429.15, std_dev = 3.9\n"
    "Test 'block_write_MiBps' running .. (control: test_timeout = 10s, "
    "test_iterations = 5, fio_ops = write)\n"
    "[Error] Test 'block_write_MiBps' time-out after 150 seconds\n"
    "[cleanup] Sent SIGKILL to process group 14797 (test 'block_write_MiBps')\n"
    "Test 'block_write_MiBps' failed: 'TestTimeout'. Continuing.\n"
    "Test 'block_random_read_MiBps' running .. (control: test_timeout = 10s)\n"
)

# A functional (non-timeout) failure: FAILED without any timeout marker.
_FUNCTIONAL_FAIL_STDOUT = (
    "Test 'block_write_MiBps' running .. (control: test_timeout = 10s)\n"
    "Test 'block_write_MiBps' failed: 'FioError'. Continuing.\n"
)


def _make_tool() -> CloudHypervisorTests:
    tool = CloudHypervisorTests.__new__(CloudHypervisorTests)
    tool._log = MagicMock()
    return tool


def _failed_entry(name: str = "block_write_MiBps") -> Dict[str, Any]:
    return {
        "name": name,
        "mean": 0.0,
        "std_dev": 0.0,
        "max": 0.0,
        "min": 0.0,
        "status": "FAILED",
    }


def _passed_entry(
    name: str = "block_write_MiBps", mean: float = 415.2
) -> Dict[str, Any]:
    return {
        "name": name,
        "mean": mean,
        "std_dev": 3.9,
        "max": mean + 5,
        "min": mean - 5,
        "status": "PASSED",
    }


class DetectTimedOutMetricsTestCase(TestCase):
    def test_detects_metric_failed_by_harness_timeout(self) -> None:
        tool = _make_tool()
        per_test = {
            "block_read_MiBps": _passed_entry("block_read_MiBps", 429.1),
            "block_write_MiBps": _failed_entry(),
        }
        self.assertEqual(
            tool._detect_timed_out_metrics(_TIMEOUT_STDOUT, per_test),
            ["block_write_MiBps"],
        )

    def test_functional_failure_is_not_treated_as_timeout(self) -> None:
        tool = _make_tool()
        per_test = {"block_write_MiBps": _failed_entry()}
        self.assertEqual(
            tool._detect_timed_out_metrics(_FUNCTIONAL_FAIL_STDOUT, per_test),
            [],
        )

    def test_timeout_marker_but_report_passed_is_ignored(self) -> None:
        # Marker present but the report entry passed -> nothing to recover.
        tool = _make_tool()
        per_test = {"block_write_MiBps": _passed_entry()}
        self.assertEqual(
            tool._detect_timed_out_metrics(_TIMEOUT_STDOUT, per_test),
            [],
        )

    def test_empty_stdout_returns_nothing(self) -> None:
        tool = _make_tool()
        per_test = {"block_write_MiBps": _failed_entry()}
        self.assertEqual(tool._detect_timed_out_metrics("", per_test), [])

    def test_unaffected_metrics_all_pass(self) -> None:
        tool = _make_tool()
        per_test = {
            "block_read_MiBps": _passed_entry("block_read_MiBps", 429.1),
            "block_write_MiBps": _passed_entry("block_write_MiBps", 415.2),
        }
        stdout = "Test 'block_read_MiBps' .. ok\nTest 'block_write_MiBps' .. ok\n"
        self.assertEqual(tool._detect_timed_out_metrics(stdout, per_test), [])


class BuildMetricsRetryCmdTestCase(TestCase):
    def test_isolated_retry_filters_single_metric_and_isolated_report(self) -> None:
        tool = _make_tool()
        cmd = tool._build_metrics_cmd_args(
            "mshv",
            None,
            only="block_write_MiBps",
            skip=None,
            report_file="lisa_metrics_report_retry_block_write_MiBps.json",
        )
        self.assertIn("--test-filter block_write_MiBps", cmd)
        self.assertIn(
            "--report-file "
            "/cloud-hypervisor/lisa_metrics_report_retry_block_write_MiBps.json",
            cmd,
        )
        # Must not clobber the primary report file.
        self.assertNotIn(f"/cloud-hypervisor/{tool.METRICS_REPORT_FILE}", cmd)
        # No global exclude on an isolated single-metric retry.
        self.assertNotIn("--test-exclude", cmd)

    def test_retry_timeout_override_is_applied(self) -> None:
        tool = _make_tool()
        cmd = tool._build_metrics_cmd_args(
            "mshv",
            45,
            only="block_write_MiBps",
            report_file="retry.json",
        )
        self.assertIn("--timeout 45", cmd)


class RetrySingleMetricTestCase(TestCase):
    def _prepare(self, tool: CloudHypervisorTests) -> None:
        tool.repo_root = PurePosixPath("/repo/cloud-hypervisor")
        tool.node = MagicMock()

    def test_retry_uses_isolated_filter_and_report(self) -> None:
        tool = _make_tool()
        self._prepare(tool)
        with patch.object(
            tool, "_run_with_enhanced_diagnostics", return_value=_run_result(0)
        ) as run_mock, patch.object(tool, "_copy_back_artifacts"), patch.object(
            tool,
            "_parse_metrics_report",
            return_value={"block_write_MiBps": _passed_entry()},
        ):
            entry = tool._retry_single_timed_out_metric(
                "mshv",
                "block_write_MiBps",
                Path("/logs"),
                None,
                numa_cmd="",
            )

        self.assertEqual(entry, _passed_entry())
        # Outer command budget must be the full-metrics budget so LISA cannot
        # preempt the metric's own configured harness timeout.
        self.assertEqual(run_mock.call_args.kwargs["timeout"], tool.PERF_CASE_TIME_OUT)
        cmd_args = run_mock.call_args.kwargs["cmd_args"]
        self.assertIn("--test-filter block_write_MiBps", cmd_args)
        self.assertIn("retry_block_write_MiBps", cmd_args)
        # Primary report file must be left untouched by the retry run.
        self.assertNotIn(
            f"/cloud-hypervisor/{tool.METRICS_REPORT_FILE} ", cmd_args + " "
        )

    def test_retry_run_lisa_exception_returns_none_but_copies_artifacts(
        self,
    ) -> None:
        tool = _make_tool()
        self._prepare(tool)
        with patch.object(
            tool,
            "_run_with_enhanced_diagnostics",
            side_effect=LisaException("timeout after N seconds"),
        ), patch.object(tool, "_copy_back_artifacts") as copy_mock:
            entry = tool._retry_single_timed_out_metric(
                "mshv", "block_write_MiBps", Path("/logs"), None, ""
            )
        self.assertIsNone(entry)
        copy_mock.assert_called_once()
        cast(MagicMock, tool._log).warning.assert_called()

    def test_retry_run_ssh_exception_is_contained(self) -> None:
        # A dropped SSH channel mid-retry must be contained (not raised) so the
        # already-collected unaffected metrics can still be reported.
        tool = _make_tool()
        self._prepare(tool)
        with patch.object(
            tool,
            "_run_with_enhanced_diagnostics",
            side_effect=SSHException("channel closed"),
        ), patch.object(tool, "_copy_back_artifacts") as copy_mock:
            entry = tool._retry_single_timed_out_metric(
                "mshv", "block_write_MiBps", Path("/logs"), None, ""
            )
        self.assertIsNone(entry)
        copy_mock.assert_called_once()
        cast(MagicMock, tool._log).warning.assert_called()

    def test_retry_run_connection_reset_is_contained(self) -> None:
        # ConnectionResetError/TimeoutError are OSError subclasses -> contained.
        tool = _make_tool()
        self._prepare(tool)
        with patch.object(
            tool,
            "_run_with_enhanced_diagnostics",
            side_effect=ConnectionResetError("reset by peer"),
        ), patch.object(tool, "_copy_back_artifacts"):
            entry = tool._retry_single_timed_out_metric(
                "mshv", "block_write_MiBps", Path("/logs"), None, ""
            )
        self.assertIsNone(entry)

    def test_report_copyback_ssh_exception_is_contained(self) -> None:
        # A transport failure while fetching the retry report is contained.
        tool = _make_tool()
        self._prepare(tool)
        cast(MagicMock, tool.node).shell.copy_back.side_effect = SSHException(
            "channel closed"
        )
        with patch.object(
            tool, "_run_with_enhanced_diagnostics", return_value=_run_result(0)
        ), patch.object(tool, "_copy_back_artifacts"):
            entry = tool._retry_single_timed_out_metric(
                "mshv", "block_write_MiBps", Path("/logs"), None, ""
            )
        self.assertIsNone(entry)
        cast(MagicMock, tool._log).warning.assert_called()

    def test_unexpected_error_propagates(self) -> None:
        # Programming errors must not be swallowed by the narrow handlers.
        tool = _make_tool()
        self._prepare(tool)
        with patch.object(
            tool,
            "_run_with_enhanced_diagnostics",
            side_effect=RuntimeError("bug"),
        ), patch.object(tool, "_copy_back_artifacts"):
            with self.assertRaises(RuntimeError):
                tool._retry_single_timed_out_metric(
                    "mshv", "block_write_MiBps", Path("/logs"), None, ""
                )

    def test_unsafe_metric_name_is_sanitized_in_filenames(self) -> None:
        tool = _make_tool()
        self._prepare(tool)
        unsafe = "../../evil block;rm -rf /"
        with patch.object(
            tool, "_run_with_enhanced_diagnostics", return_value=_run_result(0)
        ) as run_mock, patch.object(tool, "_copy_back_artifacts"), patch.object(
            tool, "_parse_metrics_report", return_value={}
        ):
            tool._retry_single_timed_out_metric("mshv", unsafe, Path("/logs"), None, "")
        cmd_args = run_mock.call_args.kwargs["cmd_args"]
        # Report file name is sanitized: no spaces, slashes, or shell metachars.
        self.assertIn(
            "lisa_metrics_report_retry_.._.._evil_block_rm_-rf__.json", cmd_args
        )
        # The raw (unsanitized) name never leaks into the report-file path.
        self.assertNotIn("retry_../../evil", cmd_args)
        self.assertNotIn("evil block;rm -rf /.json", cmd_args)
        # The raw metric name is still passed to the filter, but shlex-quoted.
        self.assertIn("--test-filter '../../evil block;rm -rf /'", cmd_args)

    def test_stale_remote_report_is_cleared_before_run(self) -> None:
        # The remote report must be deleted before the retry runs so a later
        # setup/transport failure cannot reuse a PASSED JSON from a prior run.
        tool = _make_tool()
        self._prepare(tool)
        order: List[str] = []

        def _rm(*_a: Any, **_k: Any) -> None:
            order.append("rm")

        def _run(*_a: Any, **_k: Any) -> ExecutableResult:
            order.append("run")
            return _run_result(0)

        cast(MagicMock, tool.node).execute.side_effect = _rm
        with patch.object(
            tool,
            "_run_with_enhanced_diagnostics",
            side_effect=_run,
        ), patch.object(tool, "_copy_back_artifacts"), patch.object(
            tool,
            "_parse_metrics_report",
            return_value={"block_write_MiBps": _passed_entry()},
        ):
            tool._retry_single_timed_out_metric(
                "mshv", "block_write_MiBps", Path("/logs"), None, ""
            )
        # A remote `rm -f` targeting the isolated report ran before the retry.
        self.assertEqual(order, ["rm", "run"])
        rm_cmd = cast(MagicMock, tool.node).execute.call_args.args[0]
        self.assertIn("rm -f", rm_cmd)
        self.assertIn("lisa_metrics_report_retry_block_write_MiBps.json", rm_cmd)

    def test_clear_report_transport_failure_is_contained(self) -> None:
        # A transport failure while clearing the stale report is contained and
        # never proceeds to run/merge (which could reuse a stale report).
        tool = _make_tool()
        self._prepare(tool)
        cast(MagicMock, tool.node).execute.side_effect = SSHException("no channel")
        with patch.object(
            tool, "_run_with_enhanced_diagnostics"
        ) as run_mock, patch.object(tool, "_copy_back_artifacts"):
            entry = tool._retry_single_timed_out_metric(
                "mshv", "block_write_MiBps", Path("/logs"), None, ""
            )
        self.assertIsNone(entry)
        run_mock.assert_not_called()
        cast(MagicMock, tool._log).warning.assert_called()

    def test_nonzero_exit_does_not_merge_stale_report(self) -> None:
        # Even if a (stale) report parses as a PASSED metric, a nonzero retry
        # exit code must prevent that report from recovering the timeout.
        tool = _make_tool()
        self._prepare(tool)
        with patch.object(
            tool, "_run_with_enhanced_diagnostics", return_value=_run_result(1)
        ), patch.object(tool, "_copy_back_artifacts") as copy_mock, patch.object(
            tool,
            "_parse_metrics_report",
            return_value={"block_write_MiBps": _passed_entry()},
        ) as parse_mock:
            entry = tool._retry_single_timed_out_metric(
                "mshv", "block_write_MiBps", Path("/logs"), None, ""
            )
        self.assertIsNone(entry)
        # Artifacts are still collected (copy stays in finally)...
        copy_mock.assert_called_once()
        # ...but the report is never parsed/merged after a nonzero exit.
        parse_mock.assert_not_called()
        cast(MagicMock, tool._log).warning.assert_called()

    def test_safe_name_unchanged(self) -> None:
        self.assertEqual(
            CloudHypervisorTests._sanitize_metric_name("block_write_MiBps"),
            "block_write_MiBps",
        )

    def test_unsafe_chars_collapsed(self) -> None:
        self.assertEqual(
            CloudHypervisorTests._sanitize_metric_name("../a b;c/"),
            ".._a_b_c_",
        )

    def test_empty_falls_back(self) -> None:
        self.assertEqual(CloudHypervisorTests._sanitize_metric_name("/"), "_")
        self.assertEqual(CloudHypervisorTests._sanitize_metric_name(""), "metric")


class IsValidRetryMetricTestCase(TestCase):
    def test_valid_positive_finite_mean(self) -> None:
        tool = _make_tool()
        self.assertTrue(tool._is_valid_retry_metric(_passed_entry(mean=415.2)))

    def test_none_or_failed_is_invalid(self) -> None:
        tool = _make_tool()
        self.assertFalse(tool._is_valid_retry_metric(None))
        self.assertFalse(tool._is_valid_retry_metric(_failed_entry()))

    def test_zero_and_negative_mean_invalid(self) -> None:
        tool = _make_tool()
        self.assertFalse(tool._is_valid_retry_metric(_passed_entry(mean=0.0)))
        self.assertFalse(tool._is_valid_retry_metric(_passed_entry(mean=-1.0)))

    def test_non_finite_and_non_numeric_invalid(self) -> None:
        tool = _make_tool()
        self.assertFalse(tool._is_valid_retry_metric(_passed_entry(mean=float("nan"))))
        self.assertFalse(tool._is_valid_retry_metric(_passed_entry(mean=float("inf"))))
        bad = _passed_entry()
        bad["mean"] = "429.1"
        self.assertFalse(tool._is_valid_retry_metric(bad))
        boolish = _passed_entry()
        boolish["mean"] = True
        self.assertFalse(tool._is_valid_retry_metric(boolish))


class RecoverTimedOutMetricsTestCase(TestCase):
    def _base_results(self) -> Dict[str, Any]:
        return {
            "block_read_MiBps": _passed_entry("block_read_MiBps", 429.1),
            "block_write_MiBps": _failed_entry(),
        }

    def test_successful_retry_merges_result(self) -> None:
        tool = _make_tool()
        per_test = self._base_results()
        result = _result(_TIMEOUT_STDOUT)
        recovered = _passed_entry(mean=415.2)
        with patch.object(
            tool, "_retry_single_timed_out_metric", return_value=recovered
        ) as retry_mock:
            recovered_names = tool._recover_timed_out_metrics(
                hypervisor="mshv",
                log_path=Path("/logs"),
                result=result,
                per_test_results=per_test,
                subtest_timeout=None,
                numa_cmd="",
            )
        retry_mock.assert_called_once()
        self.assertEqual(recovered_names, ["block_write_MiBps"])
        self.assertEqual(per_test["block_write_MiBps"], recovered)
        self.assertEqual(per_test["block_write_MiBps"]["status"], "PASSED")
        # Unaffected metric untouched.
        self.assertEqual(per_test["block_read_MiBps"]["status"], "PASSED")

    def test_repeated_timeout_keeps_failure(self) -> None:
        tool = _make_tool()
        per_test = self._base_results()
        result = _result(_TIMEOUT_STDOUT)
        with patch.object(
            tool, "_retry_single_timed_out_metric", return_value=_failed_entry()
        ):
            tool._recover_timed_out_metrics(
                "mshv", Path("/logs"), result, per_test, None, ""
            )
        self.assertEqual(per_test["block_write_MiBps"]["status"], "FAILED")

    def test_zero_valued_retry_keeps_failure(self) -> None:
        tool = _make_tool()
        per_test = self._base_results()
        result = _result(_TIMEOUT_STDOUT)
        with patch.object(
            tool,
            "_retry_single_timed_out_metric",
            return_value=_passed_entry(mean=0.0),
        ):
            tool._recover_timed_out_metrics(
                "mshv", Path("/logs"), result, per_test, None, ""
            )
        self.assertEqual(per_test["block_write_MiBps"]["status"], "FAILED")
        self.assertEqual(per_test["block_write_MiBps"]["mean"], 0.0)

    def test_no_timeout_does_not_retry(self) -> None:
        tool = _make_tool()
        per_test = {
            "block_read_MiBps": _passed_entry("block_read_MiBps", 429.1),
            "block_write_MiBps": _passed_entry("block_write_MiBps", 415.2),
        }
        result = _result("Test 'block_write_MiBps' .. ok\n")
        with patch.object(tool, "_retry_single_timed_out_metric") as retry_mock:
            tool._recover_timed_out_metrics(
                "mshv", Path("/logs"), result, per_test, None, ""
            )
        retry_mock.assert_not_called()

    def test_disabled_policy_skips_retry(self) -> None:
        tool = _make_tool()
        tool.METRICS_TIMEOUT_RETRY_ENABLED = False
        per_test = self._base_results()
        result = _result(_TIMEOUT_STDOUT)
        with patch.object(tool, "_retry_single_timed_out_metric") as retry_mock:
            recovered = tool._recover_timed_out_metrics(
                "mshv", Path("/logs"), result, per_test, None, ""
            )
        retry_mock.assert_not_called()
        self.assertEqual(recovered, [])
        self.assertEqual(per_test["block_write_MiBps"]["status"], "FAILED")


def _report_document() -> Dict[str, Any]:
    return {
        "git_human_readable": "msft/v52.0.127",
        "git_revision": "abc123",
        "date": "Tue Aug  4 00:35:49 UTC 2026",
        "results": [
            _passed_entry("block_read_MiBps", 429.1),
            _failed_entry("block_write_MiBps"),
        ],
    }


class WriteFinalMergedReportTestCase(TestCase):
    def test_merged_report_preserves_original_and_records_recovery(self) -> None:
        tool = _make_tool()
        with TemporaryDirectory() as tmp:
            original = Path(tmp) / CloudHypervisorTests.METRICS_REPORT_FILE
            final = Path(tmp) / CloudHypervisorTests.METRICS_FINAL_REPORT_FILE
            with open(original, "w") as f:
                json.dump(_report_document(), f)

            merged_entry = _passed_entry("block_write_MiBps", 415.2)
            per_test = {
                "block_read_MiBps": _passed_entry("block_read_MiBps", 429.1),
                "block_write_MiBps": merged_entry,
            }
            tool._write_final_merged_report(
                original, final, per_test, ["block_write_MiBps"]
            )

            # Original untouched: first-attempt timeout evidence preserved.
            with open(original) as f:
                original_doc = json.load(f)
            orig_write = _entry_by_name(original_doc, "block_write_MiBps")
            self.assertEqual(orig_write["status"], "FAILED")
            self.assertEqual(orig_write["mean"], 0.0)
            self.assertNotIn("lisa_timeout_recovered", original_doc)

            # Merged report reflects the final recovered result + metadata.
            with open(final) as f:
                final_doc = json.load(f)
            final_write = _entry_by_name(final_doc, "block_write_MiBps")
            self.assertEqual(final_write["status"], "PASSED")
            self.assertEqual(final_write["mean"], 415.2)
            self.assertEqual(final_doc["lisa_timeout_recovered"], ["block_write_MiBps"])
            self.assertEqual(final_doc["git_revision"], "abc123")

    def test_missing_original_report_is_handled(self) -> None:
        tool = _make_tool()
        with TemporaryDirectory() as tmp:
            final = Path(tmp) / CloudHypervisorTests.METRICS_FINAL_REPORT_FILE
            tool._write_final_merged_report(
                Path(tmp) / "does-not-exist.json", final, {}, ["block_write_MiBps"]
            )
            self.assertFalse(final.exists())
            cast(MagicMock, tool._log).warning.assert_called()


def _entry_by_name(document: Dict[str, Any], name: str) -> Dict[str, Any]:
    for entry in document["results"]:
        if entry["name"] == name:
            return cast(Dict[str, Any], entry)
    raise AssertionError(f"{name} not in report")


class RunMetricsTestsWiringTestCase(TestCase):
    def _make_wired_tool(self, log_path: Path) -> CloudHypervisorTests:
        tool = CloudHypervisorTests.__new__(CloudHypervisorTests)
        tool._log = MagicMock()
        tool._metrics_disk_device = ""
        tool.perf_stable_enabled = False
        tool.repo_root = PurePosixPath("/repo/cloud-hypervisor")
        tool.node = MagicMock()
        tool.node.features.is_supported.return_value = False
        # A real original report on disk so the merged report can be written.
        with open(log_path / CloudHypervisorTests.METRICS_REPORT_FILE, "w") as f:
            json.dump(_report_document(), f)
        return tool

    def _run(
        self,
        tool: CloudHypervisorTests,
        log_path: Path,
        parse_side_effect: List[Dict[str, Any]],
        sent: List[Any],
        run_side_effect: Any = None,
    ) -> None:
        def _record(**kwargs: Any) -> None:
            sent.append(kwargs)

        if run_side_effect is None:
            run_side_effect = [
                SimpleNamespace(stdout=_TIMEOUT_STDOUT, exit_code=0),
                SimpleNamespace(stdout="", exit_code=0),
            ]

        with patch.object(tool, "_setup_disk_for_metrics"), patch.object(
            tool, "_ensure_host_setup"
        ), patch.object(
            tool,
            "_run_with_enhanced_diagnostics",
            side_effect=run_side_effect,
        ), patch.object(
            tool, "_copy_back_artifacts"
        ), patch.object(
            tool, "_parse_metrics_report", side_effect=parse_side_effect
        ), patch.object(
            tool, "_check_test_panic_from_logs"
        ), patch.object(
            tool, "_save_kernel_logs"
        ), patch.object(
            tool, "_extract_diagnostic_info", return_value=""
        ), patch(
            f"{_MODULE}.send_sub_test_result_message", side_effect=_record
        ):
            tool.run_metrics_tests(MagicMock(), "mshv", log_path, subtest_timeout=None)

    def test_timeout_recovered_end_to_end(self) -> None:
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp)
            tool = self._make_wired_tool(log_path)
            sent: List[Any] = []
            self._run(
                tool,
                log_path,
                parse_side_effect=[
                    {
                        "block_read_MiBps": _passed_entry("block_read_MiBps", 429.1),
                        "block_write_MiBps": _failed_entry(),
                    },
                    {"block_write_MiBps": _passed_entry("block_write_MiBps", 415.2)},
                ],
                sent=sent,
            )

            statuses = {c["test_case_name"]: c["test_status"] for c in sent}
            self.assertEqual(statuses["block_read_MiBps"], TestStatus.PASSED)
            # Final subtest report reflects the merged (recovered) result.
            self.assertEqual(statuses["block_write_MiBps"], TestStatus.PASSED)
            # Structured merged report emitted; original preserved.
            final = log_path / CloudHypervisorTests.METRICS_FINAL_REPORT_FILE
            self.assertTrue(final.exists())
            cast(MagicMock, tool.node).mark_dirty.assert_called_once()

    def test_persistent_timeout_fails_assertion_end_to_end(self) -> None:
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp)
            tool = self._make_wired_tool(log_path)
            sent: List[Any] = []
            with self.assertRaises(AssertionError):
                self._run(
                    tool,
                    log_path,
                    parse_side_effect=[
                        {
                            "block_read_MiBps": _passed_entry(
                                "block_read_MiBps", 429.1
                            ),
                            "block_write_MiBps": _failed_entry(),
                        },
                        {"block_write_MiBps": _failed_entry()},
                    ],
                    sent=sent,
                )
            statuses = {c["test_case_name"]: c["test_status"] for c in sent}
            self.assertEqual(statuses["block_write_MiBps"], TestStatus.FAILED)
            # No merged report when nothing recovered.
            final = log_path / CloudHypervisorTests.METRICS_FINAL_REPORT_FILE
            self.assertFalse(final.exists())

    def test_retry_ssh_failure_still_reports_unaffected_metrics(self) -> None:
        # The reviewer's core concern: an SSH/transport failure during the
        # isolated retry must not escape before the already-collected
        # unaffected metrics are reported. Containment keeps the original
        # timeout failure and reports every metric; the run still fails the
        # final assertion (AssertionError, not SSHException).
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp)
            tool = self._make_wired_tool(log_path)
            sent: List[Any] = []
            with self.assertRaises(AssertionError):
                self._run(
                    tool,
                    log_path,
                    parse_side_effect=[
                        {
                            "block_read_MiBps": _passed_entry(
                                "block_read_MiBps", 429.1
                            ),
                            "block_write_MiBps": _failed_entry(),
                        },
                    ],
                    sent=sent,
                    run_side_effect=[
                        SimpleNamespace(stdout=_TIMEOUT_STDOUT, exit_code=0),
                        SSHException("channel closed during retry"),
                    ],
                )
            statuses = {c["test_case_name"]: c["test_status"] for c in sent}
            # Unaffected metric was still reported despite the retry SSH failure.
            self.assertEqual(statuses["block_read_MiBps"], TestStatus.PASSED)
            self.assertEqual(statuses["block_write_MiBps"], TestStatus.FAILED)

    def test_nonzero_retry_does_not_recover_via_stale_report(self) -> None:
        # End-to-end: the retry run exits nonzero but a (stale) report would
        # parse as PASSED. The nonzero exit must block recovery, so the metric
        # stays FAILED and no merged report is written.
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp)
            tool = self._make_wired_tool(log_path)
            sent: List[Any] = []
            with self.assertRaises(AssertionError):
                self._run(
                    tool,
                    log_path,
                    parse_side_effect=[
                        {
                            "block_read_MiBps": _passed_entry(
                                "block_read_MiBps", 429.1
                            ),
                            "block_write_MiBps": _failed_entry(),
                        },
                        # A stale PASSED report that must NOT be consulted.
                        {"block_write_MiBps": _passed_entry("block_write_MiBps")},
                    ],
                    sent=sent,
                    run_side_effect=[
                        SimpleNamespace(stdout=_TIMEOUT_STDOUT, exit_code=0),
                        SimpleNamespace(stdout="", exit_code=1),
                    ],
                )
            statuses = {c["test_case_name"]: c["test_status"] for c in sent}
            self.assertEqual(statuses["block_read_MiBps"], TestStatus.PASSED)
            self.assertEqual(statuses["block_write_MiBps"], TestStatus.FAILED)
            final = log_path / CloudHypervisorTests.METRICS_FINAL_REPORT_FILE
            self.assertFalse(final.exists())
