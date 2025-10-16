# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Dict, List, Optional, Set, Tuple, Type

from assertpy.assertpy import assert_that, fail

from lisa import Node
from lisa.executable import ExecutableResult, Tool
from lisa.features import SerialConsole
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.operating_system import CBLMariner, Ubuntu
from lisa.testsuite import TestResult
from lisa.tools import (
    Cat,
    Chmod,
    Chown,
    Dmesg,
    Docker,
    Echo,
    Git,
    Ls,
    Lsblk,
    Mkdir,
    Modprobe,
    Sed,
    Whoami,
)
from lisa.util import LisaException, UnsupportedDistroException, find_groups_in_lines

# TEMPORARY: Runtime variance tracking - Remove after validation
try:
    from .numa_runtime_tracker import NumaRuntimeTracker

    NUMA_TRACKER_AVAILABLE = True
except ImportError:
    NUMA_TRACKER_AVAILABLE = False


@dataclass
class CloudHypervisorTestResult:
    name: str = ""
    status: TestStatus = TestStatus.QUEUED
    message: str = ""


class CloudHypervisorTests(Tool):
    CMD_TIME_OUT = 3600
    # Slightly higher case timeout to give the case a window to
    # - list subtests before running the tests.
    # - extract sub test results from stdout and report them.
    CASE_TIME_OUT = CMD_TIME_OUT + 1200
    # 2 Hrs of timeout for perf tests and 2400 seconds for other operations
    PERF_CASE_TIME_OUT = 7200 + 2400
    PERF_CMD_TIME_OUT = 1200

    upstream_repo = "https://github.com/cloud-hypervisor/cloud-hypervisor.git"
    env_vars = {
        "RUST_BACKTRACE": "full",
    }

    ms_clh_repo = ""
    use_ms_clh_repo = False
    ms_access_token = ""
    clh_guest_vm_type = ""
    use_ms_guest_kernel = ""
    use_ms_hypervisor_fw = ""
    use_ms_ovmf_fw = ""
    use_ms_bz_image = ""

    # Block perf related env var
    use_datadisk = ""
    use_pmem = ""
    """
    Following is the last usable entry in e820 table and is safest to use for
    pmem since its most likely to be free. 0x0000001000000000 is 64G.
    So, set it as default.

    [    0.000000] BIOS-e820: [mem 0x0000001000000000-0x00000040ffffffff] usable

    """
    pmem_config = "memmap=8G!64G"
    disable_disk_cache = ""
    mibps_block_size_kb = ""
    iops_block_size_kb = ""

    cmd_path: PurePath
    repo_root: PurePath

    # TEMPORARY: Runtime tracker storage (persists across suite iterations)
    # Key: testcase name, Value: NumaRuntimeTracker instance
    _runtime_trackers: Dict[str, Any] = {}

    @property
    def command(self) -> str:
        return str(self.cmd_path)

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Docker]

    def _sanitize_name(self, s: str) -> str:
        """Sanitize names for filenames: keep alphanumeric, dot, dash, underscore."""
        return re.sub(r"[^A-Za-z0-9_.-]", "_", s)

    def _prepare_subtests(
        self,
        test_type: str,
        hypervisor: str,
        only: Optional[List[str]],
        skip: Optional[List[str]],
    ) -> Dict[str, Any]:
        """Prepare subtests and skip arguments."""
        subtests = self._list_subtests(hypervisor, test_type)
        # Store the ordered list for diagnostic purposes
        self._ordered_subtests = subtests.copy()

        if only is not None:
            if not skip:
                skip = []
            # Add everything except 'only' to skip list
            skip += [t for t in subtests if t not in only]
        if skip is not None:
            subtests = [t for t in subtests if t not in skip]
            skip_args = " ".join(map(lambda t: f"--skip {t}", skip))
        else:
            skip_args = ""
        self._log.debug(f"Final Subtests list to run: {subtests}")

        return {"subtest_set": set(subtests), "skip_args": skip_args}

    def _configure_environment_if_needed(self, hypervisor: str) -> None:
        """Configure environment specific settings if needed."""
        if isinstance(self.node.os, CBLMariner) and hypervisor == "mshv":
            # Install dependency to create VDPA Devices
            self.node.os.install_packages(["iproute", "iproute-devel"])
            # Load VDPA kernel module and create devices
            self._configure_vdpa_devices(self.node)

    def _handle_test_failure_with_diagnostics(
        self,
        base_message: str,
        result: ExecutableResult,
        test_type: str,
        hypervisor: str,
        log_path: Path,
    ) -> None:
        """Handle test failure with diagnostic context and enhanced error reporting."""
        diagnostic_info = self._extract_diagnostic_info(
            log_path, f"ch_{test_type}_{hypervisor}", result
        )
        failure_msg = base_message
        if diagnostic_info:
            failure_msg += f" | {diagnostic_info}"
        fail(failure_msg)

    def _handle_timeout_failure(
        self,
        result: ExecutableResult,
        failures: List[str],
        test_type: str,
        hypervisor: str,
        log_path: Path,
    ) -> None:
        """Handle timeout with failures."""
        base_message = (
            f"Timed out after {result.elapsed:.2f}s with failures: {failures[:3]}"
        )
        self._handle_test_failure_with_diagnostics(
            base_message, result, test_type, hypervisor, log_path
        )

    def _handle_timeout_only(
        self, result: ExecutableResult, test_type: str, hypervisor: str, log_path: Path
    ) -> None:
        """Handle pure timeout without test failures."""
        base_message = f"Timed out after {result.elapsed:.2f}s"
        self._handle_test_failure_with_diagnostics(
            base_message, result, test_type, hypervisor, log_path
        )

    def _handle_test_failures(
        self,
        failures: List[str],
        test_type: str,
        hypervisor: str,
        log_path: Path,
        result: ExecutableResult,
    ) -> None:
        """Handle test failures with diagnostic context."""
        base_message = f"Unexpected failures: {failures[:3]}"
        self._handle_test_failure_with_diagnostics(
            base_message, result, test_type, hypervisor, log_path
        )

    def _handle_exit_code_failure(
        self, result: ExecutableResult, test_type: str, hypervisor: str, log_path: Path
    ) -> None:
        """Handle non-zero exit code failures."""
        # Extract any test failures from output even if we couldn't parse results
        failing_test_pattern = r"test (\S+) \.\.\. FAILED"
        failing_tests = re.findall(failing_test_pattern, result.stdout)

        if failing_tests:
            # We have specific test failures - use the general handler
            base_message = f"Unexpected failures: {failing_tests[:3]}"
            self._handle_test_failure_with_diagnostics(
                base_message, result, test_type, hypervisor, log_path
            )
        else:
            # No specific test failures found, get diagnostics and handle differently
            diagnostic_info = self._extract_diagnostic_info(
                log_path, f"ch_{test_type}_{hypervisor}", result
            )
            self._handle_process_crash_or_failure(
                result, test_type, hypervisor, log_path, diagnostic_info
            )

    def _handle_process_crash_or_failure(
        self,
        result: ExecutableResult,
        test_type: str,
        hypervisor: str,
        log_path: Path,
        diagnostic_info: Optional[str] = None,
    ) -> None:
        """Handle process crashes or other failures."""
        if diagnostic_info is None:
            diagnostic_info = self._extract_diagnostic_info(
                log_path, f"ch_{test_type}_{hypervisor}", result
            )

        if diagnostic_info:
            fail(
                f"Test process failed with exit code {result.exit_code}. "
                f"{diagnostic_info}"
            )
        else:
            self._handle_fallback_error_detection(result)

    def _handle_fallback_error_detection(self, result: ExecutableResult) -> None:
        """Handle fallback error detection for crashes."""
        if "fatal runtime error" in result.stdout or "SIGABRT" in result.stdout:
            # Extract the error context
            lines = result.stdout.split("\n")
            error_context: List[str] = []
            for i, line in enumerate(lines):
                if "fatal runtime error" in line or "SIGABRT" in line:
                    # Get a few lines around the error
                    start = max(0, i - 2)
                    end = min(len(lines), i + 3)
                    error_context = lines[start:end]
                    break
            fail(
                f"Test process crashed with exit code {result.exit_code}. "
                f"Error: {' '.join(error_context)}"
            )
        else:
            fail(
                f"Test process failed with exit code {result.exit_code}. "
                "Check logs for details."
            )

    def _process_test_results(
        self,
        result: ExecutableResult,
        test_result: TestResult,
        test_type: str,
        hypervisor: str,
        log_path: Path,
        subtests: Set[str],
    ) -> None:
        """Process test results and handle various failure scenarios."""
        # Report subtest results and collect logs before doing any assertions.
        results = self._extract_test_results(result.stdout, log_path, subtests)
        failures = [r.name for r in results if r.status == TestStatus.FAILED]

        for r in results:
            send_sub_test_result_message(
                test_result=test_result,
                test_case_name=r.name,
                test_status=r.status,
                test_message=r.message,
            )

        self._save_kernel_logs(log_path)

        has_failures = len(failures) > 0
        if result.is_timeout and has_failures:
            self._handle_timeout_failure(
                result, failures, test_type, hypervisor, log_path
            )
        elif result.is_timeout:
            self._handle_timeout_only(result, test_type, hypervisor, log_path)
        elif has_failures:
            self._handle_test_failures(
                failures, test_type, hypervisor, log_path, result
            )
        elif result.exit_code != 0:
            self._handle_exit_code_failure(result, test_type, hypervisor, log_path)
        else:
            # The command could have failed before starting test case execution.
            result.assert_exit_code()

    def run_tests(
        self,
        test_result: TestResult,
        test_type: str,
        hypervisor: str,
        log_path: Path,
        ref: str = "",
        only: Optional[List[str]] = None,
        skip: Optional[List[str]] = None,
    ) -> None:
        if ref:
            self.node.tools[Git].checkout(ref, self.repo_root)

        subtests = self._prepare_subtests(test_type, hypervisor, only, skip)
        self._configure_environment_if_needed(hypervisor)

        # Use enhanced diagnostics for better debugging and monitoring
        skip_args = subtests["skip_args"]
        cmd_args = f"tests --hypervisor {hypervisor} --{test_type} -- -- {skip_args}"
        # normalize name so artifacts are predictable (no spaces/colons/slashes)
        safe_test_type = self._sanitize_name(test_type.replace("-", "_"))
        test_name = self._sanitize_name(f"ch_{safe_test_type}_{hypervisor}")

        try:
            result = self._run_with_enhanced_diagnostics(
                cmd_args=cmd_args,
                timeout=self.CMD_TIME_OUT,
                log_path=log_path,
                test_name=test_name,
            )
        finally:
            # Always copy back artifacts, even on failure/timeout
            self._copy_back_artifacts(log_path, test_name)

        self._process_test_results(
            result,
            test_result,
            test_type,
            hypervisor,
            log_path,
            subtests["subtest_set"],
        )

    def run_metrics_tests(
        self,
        test_result: TestResult,
        hypervisor: str,
        log_path: Path,
        ref: str = "",
        only: Optional[List[str]] = None,
        skip: Optional[List[str]] = None,
        subtest_timeout: Optional[int] = None,
    ) -> None:
        self._setup_disk_for_metrics(log_path)

        if ref:
            self.node.tools[Git].checkout(ref, self.repo_root)

        subtests = self._prepare_metrics_subtests(hypervisor, only, skip)
        failed_testcases: List[str] = []

        for testcase in subtests:
            status, metrics, trace = self._run_single_metrics_test(
                testcase, hypervisor, log_path, subtest_timeout
            )

            if status == TestStatus.FAILED:
                failed_testcases.append(testcase)

            self._send_metrics_test_result(
                test_result, testcase, status, metrics, trace
            )
            self._write_testcase_log(log_path, testcase, trace)

        self._save_kernel_logs(log_path)

        # TEMPORARY: Print final runtime tracker summaries for all tests
        self._print_final_runtime_summaries(log_path)

        assert_that(
            failed_testcases, f"Failed Testcases: {failed_testcases}"
        ).is_empty()

    def _setup_disk_for_metrics(self, log_path: Path) -> None:
        """Setup disk for metrics tests if needed."""
        disk_name = ""
        if self.use_pmem:
            disk_name = self._get_pmem_for_block_tests()
        elif self.use_datadisk:
            disk_name = self._get_data_disk_for_block_tests()

        if disk_name:
            self._log.debug(f"Using disk: {disk_name}, for block tests")
            self.env_vars["DATADISK_NAME"] = disk_name
            self._save_kernel_logs(log_path)

    def _prepare_metrics_subtests(
        self, hypervisor: str, only: Optional[List[str]], skip: Optional[List[str]]
    ) -> Set[str]:
        """Prepare subtests for metrics testing."""
        subtests = self._list_perf_metrics_tests(hypervisor=hypervisor)

        if only is not None:
            if not skip:
                skip = []
            # Add everything except 'only' to skip list
            skip += list(subtests.difference(only))
        if skip is not None:
            subtests.difference_update(skip)

        self._log.debug(f"Final Subtests list to run: {subtests}")
        return subtests

    def _run_single_metrics_test(
        self,
        testcase: str,
        hypervisor: str,
        log_path: Path,
        subtest_timeout: Optional[int],
    ) -> Tuple[TestStatus, str, str]:
        """Run a single metrics test and return status, metrics, trace."""
        status: TestStatus = TestStatus.QUEUED
        metrics: str = ""
        trace: str = ""
        result = None

        # TEMPORARY: Get or create runtime tracker for this test
        # (persists across iterations)
        tracker = None
        if NUMA_TRACKER_AVAILABLE:
            if testcase not in self._runtime_trackers:
                # First time seeing this test - create new tracker
                self._runtime_trackers[testcase] = NumaRuntimeTracker(
                    test_name=testcase
                )
                self._log.debug(
                    f"Created new runtime tracker for {testcase}"
                )
            tracker = self._runtime_trackers[testcase]

        self._set_block_size_env_var(testcase)
        cmd_args = self._build_metrics_cmd_args(testcase, hypervisor, subtest_timeout)

        try:
            cmd_timeout = self._get_metrics_timeout()
            safe_tc = self._sanitize_name(testcase)
            test_name = f"ch_metrics_{safe_tc}_{hypervisor}"

            try:
                result = self._run_with_enhanced_diagnostics(
                    cmd_args=cmd_args,
                    timeout=cmd_timeout,
                    log_path=log_path,
                    test_name=test_name,
                )
            finally:
                self._copy_back_artifacts(log_path, test_name)

            status, metrics, trace = self._process_metrics_result(
                result, testcase, log_path, test_name
            )

            # TEMPORARY: Record iteration in tracker (if available and test passed)
            if tracker and status == TestStatus.PASSED and metrics:
                self._record_iteration_in_tracker(
                    tracker, metrics, result, testcase, log_path
                )

        except Exception as e:
            self._log.info(f"Testcase failed, tescase name: {testcase}")
            status = TestStatus.FAILED
            trace = str(e)
            result = None

        # TEMPORARY: Print tracker summary at end of test (if available)
        # Shows cumulative stats across all iterations so far
        if tracker and tracker.iterations:
            # Set configuration (baseline = NUMA disabled)
            numa_config = {
                "numa_enabled": False,
                "policy": None,
                "numa_node": None,
                "cross_numa_access": False,
                "irq_affinity": {"enabled": False},
            }
            tracker.numa_config = numa_config

            iteration_count = len(tracker.iterations)
            self._log.info(f"\n{'='*80}")
            self._log.info(
                f"Runtime Statistics for {testcase} "
                f"(Iteration {iteration_count} cumulative)"
            )
            self._log.info(f"{'='*80}")
            tracker.print_summary()

            # Only show detailed iteration table if we have multiple iterations
            if iteration_count > 1:
                tracker.print_iterations_table()

            # Save to JSON for post-analysis (overwrites with latest cumulative data)
            saved_file = tracker.save_summary(log_path)
            self._log.info(
                f"\nCumulative summary ({iteration_count} iterations) "
                f"saved to: {saved_file}"
            )

        # Store result for log writing
        self._last_result = result
        return status, metrics, trace

    def _print_final_runtime_summaries(self, log_path: Path) -> None:
        """
        TEMPORARY: Print final runtime statistics for all tracked tests.

        This method is called at the end of the test suite (after all iterations).
        It provides a comprehensive summary of all tests with variance analysis.
        Will be removed after Phase 3 validation.
        """
        if not NUMA_TRACKER_AVAILABLE or not self._runtime_trackers:
            return

        self._log.info(f"\n\n{'='*80}")
        self._log.info("FINAL RUNTIME STATISTICS - ALL TESTS")
        self._log.info(f"{'='*80}\n")

        # Sort tests by name for consistent output
        for testcase in sorted(self._runtime_trackers.keys()):
            tracker = self._runtime_trackers[testcase]

            if not tracker.iterations:
                continue

            iteration_count = len(tracker.iterations)
            summary = tracker.get_summary()

            self._log.info(f"\n{testcase}:")
            self._log.info(f"  Iterations: {iteration_count}")
            self._log.info(f"  Mean: {summary.mean:.2f} {summary.unit}")
            self._log.info(
                f"  CV%: {summary.cv_percent:.1f}% "
                f"({self._get_variance_quality(summary.cv_percent)})"
            )

            # Show baseline comparison if available
            baseline_file = log_path / f"{testcase}_baseline_runtime_summary.json"
            if baseline_file.exists():
                try:
                    comparison = tracker.compare_with_baseline(str(baseline_file))
                    if comparison and "error" not in comparison:
                        perf_diff = comparison["performance_diff_percent"]
                        var_improve = comparison["variance_improvement_percent"]
                        self._log.info(
                            f"  vs Baseline: {perf_diff:+.1f}% performance, "
                            f"{var_improve:+.1f}% variance"
                        )
                except Exception as e:
                    self._log.debug(f"Could not compare with baseline: {e}")

        self._log.info(f"\n{'='*80}")
        self._log.info(
            f"All runtime summaries saved to: {log_path}/*_runtime_summary.json"
        )
        self._log.info(f"{'='*80}\n")

    def _get_variance_quality(self, cv_percent: float) -> str:
        """Get variance quality indicator based on CV%."""
        if cv_percent < 5:
            return "Excellent"
        elif cv_percent < 10:
            return "Good"
        elif cv_percent < 20:
            return "Moderate"
        else:
            return "High"

    def _build_metrics_cmd_args(
        self, testcase: str, hypervisor: str, subtest_timeout: Optional[int]
    ) -> str:
        """Build command arguments for metrics test."""
        cmd_args = (
            f"tests --hypervisor {hypervisor} --metrics -- --"
            f" --test-filter {testcase}"
        )
        if subtest_timeout:
            cmd_args = f"{cmd_args} --timeout {subtest_timeout}"
        return cmd_args

    def _get_metrics_timeout(self) -> int:
        """Get timeout for metrics tests."""
        cmd_timeout = self.PERF_CMD_TIME_OUT
        if self.clh_guest_vm_type == "CVM":
            cmd_timeout = cmd_timeout + 300
        return cmd_timeout

    def _process_metrics_result(
        self, result: ExecutableResult, testcase: str, log_path: Path, test_name: str
    ) -> Tuple[TestStatus, str, str]:
        """Process the result of a metrics test."""
        if result.exit_code == 0:
            status = TestStatus.PASSED
            metrics = self._process_perf_metric_test_result(result.stdout)
            trace = ""
        else:
            status = TestStatus.FAILED
            metrics = ""
            # Get enhanced diagnostic information for better error reporting
            diagnostic_info = self._extract_diagnostic_info(log_path, test_name, result)
            if diagnostic_info:
                trace = f"Testcase '{testcase}' failed: {diagnostic_info}"
            else:
                trace = (
                    f"Testcase '{testcase}' failed with exit code "
                    f"{result.exit_code}"
                )

        return status, metrics, trace

    def _send_metrics_test_result(
        self,
        test_result: TestResult,
        testcase: str,
        status: TestStatus,
        metrics: str,
        trace: str,
    ) -> None:
        """Send metrics test result message."""
        msg = metrics if status == TestStatus.PASSED else trace
        send_sub_test_result_message(
            test_result=test_result,
            test_case_name=testcase,
            test_status=status,
            test_message=msg,
        )

    def _write_testcase_log(self, log_path: Path, testcase: str, trace: str) -> None:
        """Write testcase log to file."""
        testcase_log_file = log_path.joinpath(f"{testcase}.log")
        with open(testcase_log_file, "w") as f:
            if hasattr(self, "_last_result") and self._last_result is not None:
                f.write(self._last_result.stdout)
            else:
                f.write(f"Test failed before execution: {trace}")

    def _extract_diagnostic_info(
        self, log_path: Path, test_name: str, result: Any
    ) -> str:
        """
        Extract meaningful error information from enhanced diagnostic files and stdout.
        Returns a concise but informative error description.
        """
        diagnostic_messages: List[str] = []

        # 1. Extract information from stdout
        if hasattr(result, "stdout") and result.stdout:
            diagnostic_messages.extend(self._extract_stdout_diagnostics(result.stdout))

        # 2. Extract information from diagnostic files
        diagnostic_messages.extend(self._extract_file_diagnostics(log_path, test_name))

        # 3. Return consolidated diagnostic info
        if diagnostic_messages:
            return " | ".join(diagnostic_messages[:3])

        # 4. Fallback: extract basic error information from stdout/stderr
        if hasattr(result, "stdout") and result.stdout:
            fallback_msg = self._extract_fallback_error_info(result.stdout)
            if fallback_msg:
                return fallback_msg

        # 5. Last resort: basic exit code info
        if hasattr(result, "exit_code") and result.exit_code != 0:
            return f"Process exited with code {result.exit_code}"

        return ""

    def _extract_stdout_diagnostics(self, stdout: str) -> List[str]:
        """Extract diagnostic information from stdout."""
        diagnostic_messages: List[str] = []

        # Look for specific Rust test failures
        test_failure_pattern = r"test\s+(\S+)\s+\.\.\.\s+FAILED"
        failed_tests = re.findall(test_failure_pattern, stdout)
        if failed_tests:
            # Limit to 3 tests
            diagnostic_messages.append(f"Failed tests: {', '.join(failed_tests[:3])}")

        # Look for panic messages
        panic_pattern = r"thread .* panicked at '([^']+)', ([^:\n]+:\d+:\d+)"
        panics = re.findall(panic_pattern, stdout, re.MULTILINE)
        if panics:
            msg, loc = panics[0]
            diagnostic_messages.append(f"Panic: {msg[:100]}")
            diagnostic_messages.append(f"At: {loc}")

        # Look for fatal runtime errors
        fatal_match = re.search(r"(.*fatal runtime error[^\n]*)", stdout)
        if fatal_match:
            error_line = fatal_match.group(1).strip()
            # Try to find test context in the same line or nearby
            test_match = re.search(r"test (\S+)", error_line)
            if not test_match:
                # Look for test context in surrounding lines
                lines = stdout.split("\n")
                for i, line in enumerate(lines):
                    if "fatal runtime error" in line:
                        for j in range(max(0, i - 2), i):
                            test_match = re.search(r"test (\S+)", lines[j])
                            if test_match:
                                break
                        break

            if test_match:
                diagnostic_messages.append(
                    f"Fatal error in {test_match.group(1)}: {error_line[:80]}"
                )
            else:
                diagnostic_messages.append(f"Fatal error: {error_line[:100]}")

        # Look for assertion failures
        assert_pattern = r"assertion failed:.*?(?:\n|$)"
        assertions = re.findall(assert_pattern, stdout, re.MULTILINE)
        if assertions:
            assert_msg = assertions[0].strip()[:100]
            diagnostic_messages.append(f"Assertion: {assert_msg}")

        # Add "likely hung in" diagnostic for timeouts based on last successful test
        oks = re.findall(r"test\s+(\S+)\s+\.\.\.\s+ok", stdout)
        if oks and hasattr(self, "_ordered_subtests"):
            try:
                last_ok = oks[-1]
                i = self._ordered_subtests.index(last_ok)
                if i + 1 < len(self._ordered_subtests):
                    diagnostic_messages.append(
                        f"Likely hung in: {self._ordered_subtests[i + 1]}"
                    )
            except (ValueError, IndexError):
                pass

        return diagnostic_messages

    def _extract_file_diagnostics(self, log_path: Path, test_name: str) -> List[str]:
        """Extract diagnostic information from diagnostic files."""
        diagnostic_messages: List[str] = []

        log_file = log_path / f"{test_name}.log"
        core_bt_file = log_path / f"{test_name}_core_bt.txt"
        live_bt_file = log_path / f"{test_name}_live_bt.txt"

        # Check if we have core dump analysis
        if core_bt_file.exists():
            core_msg = self._extract_core_dump_info(core_bt_file)
            if core_msg:
                diagnostic_messages.extend(core_msg)

        # Check if we have live stack dumps (indicates hang)
        if live_bt_file.exists() and live_bt_file.stat().st_size > 0:
            diagnostic_messages.append("Process hung (live stacks captured)")

        # Look for watchdog messages in the main log
        if log_file.exists():
            watchdog_msg = self._extract_watchdog_info(log_file)
            if watchdog_msg:
                diagnostic_messages.append(watchdog_msg)

        return diagnostic_messages

    def _extract_core_dump_info(self, core_bt_file: Path) -> List[str]:
        """Extract information from core dump backtrace file."""
        diagnostic_messages: List[str] = []
        try:
            with open(core_bt_file, "r") as f:
                # Read first 1KB
                content = f.read(1000)
                if "Program terminated with signal" in content:
                    signal_match = re.search(
                        r"Program terminated with signal (\w+)", content
                    )
                    if signal_match:
                        diagnostic_messages.append(
                            f"Crashed with {signal_match.group(1)}"
                        )
                # Look for the crash location
                crash_location = re.search(r"#0\s+.*?in\s+(\S+)", content)
                if crash_location:
                    diagnostic_messages.append(f"Crash in: {crash_location.group(1)}")
        except Exception:
            pass
        return diagnostic_messages

    def _extract_watchdog_info(self, log_file: Path) -> str:
        """Extract watchdog information from log file."""
        try:
            with open(log_file, "r") as f:
                content = f.read()
                if "[watchdog]" in content:
                    return "Inactivity timeout detected"
        except Exception:
            pass
        return ""

    def _extract_fallback_error_info(self, stdout: str) -> str:
        """Extract basic error information from stdout as fallback."""
        error_keywords = [
            "error:",
            "Error:",
            "ERROR:",
            "failed",
            "Failed",
            "FAILED",
        ]
        lines = stdout.split("\n")
        error_lines: List[str] = []

        for line in lines:
            line = line.strip()
            if any(keyword in line for keyword in error_keywords):
                # Skip very long lines or empty lines
                if line and len(line) < 200:
                    error_lines.append(line)
                    if len(error_lines) >= 2:  # Limit to first 2 error lines
                        break

        if error_lines:
            return f"Error context: {' | '.join(error_lines)}"

        return ""

    def _run_with_enhanced_diagnostics(
        self, cmd_args: str, timeout: int, log_path: Path, test_name: str = "ch_test"
    ) -> Any:
        """
        Run Cloud Hypervisor tests with enhanced Rust diagnostics, core dumps,
        inactivity watchdog, and comprehensive logging.
        """
        # Tunables (pull from env if provided; else use sane defaults)
        idle_secs = int(os.environ.get("CH_IDLE_SECS", "600"))
        hang_kill_secs = int(os.environ.get("CH_HANG_KILL_SECS", "1800"))
        check_interval = int(os.environ.get("CH_CHECK_INTERVAL", "30"))

        # --- 1) Rich Rust diagnostics ---
        enhanced_env_vars = self.env_vars.copy()
        enhanced_env_vars.update(
            {
                "RUST_BACKTRACE": "full",
                "RUST_LIB_BACKTRACE": "1",
                # Tweak if too chatty: e.g., "cloud_hypervisor=debug,virtio=info"
                "RUST_LOG": os.environ.get("RUST_LOG", "debug"),
                "CH_IDLE_SECS": str(idle_secs),
                "CH_HANG_KILL_SECS": str(hang_kill_secs),
                "CH_CHECK_INTERVAL": str(check_interval),
            }
        )

        # --- 2 & 3) Core dumps + inactivity watchdog + tee'd logs ---
        # Writes artifacts in the working directory:
        #   - ch_test.log                   (full stdout/stderr)
        #   - ch_test_live_bt.txt           (stacks on inactivity)
        #   - ch_test_core_bt.txt           (stacks from core on nonzero exit)

        # Create a single command that runs everything on the remote VM
        # with proper bash handling
        full_cmd = f"""bash -lc '
set -o pipefail

# enable core dumps (best-effort)
ulimit -c unlimited || true
sudo sysctl -w kernel.core_pattern=core.%e.%p.%t >/dev/null 2>&1 || true

# sanity
pwd
echo "[env] RB=$RUST_BACKTRACE RLB=$RUST_LIB_BACKTRACE RLOG=$RUST_LOG"
echo "[env] CH_IDLE_SECS=${{CH_IDLE_SECS:-600}}"
echo "[env] CH_HANG_KILL_SECS=${{CH_HANG_KILL_SECS:-1800}}"
echo "[env] CH_CHECK_INTERVAL=${{CH_CHECK_INTERVAL:-30}}"
test -x scripts/dev_cli.sh || {{ echo "[error] scripts/dev_cli.sh missing"; exit 98; }}

# repo-local artifact names so LISA will collect them
log_file="{test_name}.log"
live_bt_file="{test_name}_live_bt.txt"
core_bt_file="{test_name}_core_bt.txt"

rm -f "$log_file" "$live_bt_file" "$core_bt_file"

# start tests, line-buffered if available, stream to log
if command -v stdbuf >/dev/null; then
  ( stdbuf -oL -eL scripts/dev_cli.sh {cmd_args} | tee "$log_file" ) &
else
  ( scripts/dev_cli.sh {cmd_args} | tee "$log_file" ) &
fi
pid=$!

# background watchdog that dumps stacks on inactivity
idle=0
total_idle=0
last_size=0
idle_secs=${{CH_IDLE_SECS:-600}}
check_interval=${{CH_CHECK_INTERVAL:-30}}
hang_kill_secs=${{CH_HANG_KILL_SECS:-1800}}
while kill -0 $pid 2>/dev/null; do
  sleep $check_interval
  size=$(stat -c%s "$log_file" 2>/dev/null || echo 0)
  if [ "$size" -eq "$last_size" ]; then
    idle=$((idle + check_interval))
  else
    total_idle=$((total_idle + idle))
    idle=0
    last_size=$size
  fi
  if [ "$idle" -ge "$idle_secs" ]; then
    echo "[watchdog] No log growth for ${{idle_secs}}s; dumping live stacks" \\
      | tee -a "$log_file"
    echo "[watchdog] pstree / ps snapshot" | tee -a "$log_file"
    pstree -ap 2>/dev/null | head -200 | tee -a "$log_file" || true
    ps -eo pid,ppid,stat,etime,cmd | head -200 | tee -a "$log_file" || true
    ps -eL -o pid,tid,ppid,stat,etime,comm,cmd | head -200 \\
      | tee -a "$log_file" || true

    # Find a good target: prefer the integration test binary; otherwise a child
    # of the cargo/dev_cli process; otherwise fall back to the main pid.
    tpid="$(pgrep -n -f 'target/.*/deps/integration-' || true)"
    if [ -z "$tpid" ]; then
      # newest child of $pid (often cargo test or the binary)
      tpid="$(pgrep -P "$pid" | tail -n1 || true)"
    fi
    [ -z "$tpid" ] && tpid="$pid"

    # Best-effort freeze to avoid the attach race
    sudo kill -STOP "$tpid" 2>/dev/null || true

    # Snapshot a core ASAP (prefer gcore; fall back to gdb generate-core-file)
    core_out="core.$(basename "$tpid").$(date +%s)"
    if command -v gcore >/dev/null 2>&1; then
      sudo gcore -o "$core_out" "$tpid" >/dev/null 2>&1 || true
    else
      sudo gdb -batch -p "$tpid" \\
        -ex "set pagination off" \\
        -ex "generate-core-file $core_out" \\
        -ex "detach" -ex "quit" >/dev/null 2>&1 || true
    fi

    # Then grab a concise live backtrace
    sudo gdb -batch -p "$tpid" \\
      -ex "set pagination off" \\
      -ex "set print elements 0" \\
      -ex "set backtrace limit 64" \\
      -ex "thread apply all bt" \\
      -ex "info threads" > "$live_bt_file" 2>&1 || true

    # Let it run again
    sudo kill -CONT "$tpid" 2>/dev/null || true
    total_idle=$((total_idle + idle))
    idle=0
  fi
  if [ "$total_idle" -ge "$hang_kill_secs" ]; then
    echo "[watchdog] Exceeded ${{hang_kill_secs}}s of inactivity; terminating test" \\
      | tee -a "$log_file"

    # Find target using same logic as watchdog
    tpid="$(pgrep -n -f 'target/.*/deps/integration-' || true)"
    if [ -z "$tpid" ]; then
      tpid="$(pgrep -P "$pid" | tail -n1 || true)"
    fi
    [ -z "$tpid" ] && tpid="$pid"

    kill -TERM "$tpid" 2>/dev/null || true
    kill -TERM "$pid" 2>/dev/null || true
    sleep 10
    kill -KILL "$tpid" 2>/dev/null || true
    kill -KILL "$pid" 2>/dev/null || true
    break
  fi
done &

watchdog_pid=$!

# trap to always stop watchdog
trap "kill $watchdog_pid 2>/dev/null || true" EXIT

# wait for tests
wait $pid
ec=$?

# stop watchdog
kill $watchdog_pid 2>/dev/null || true

# on failure, try to symbolize a core dump
if [ $ec -ne 0 ]; then
  core=""
  for dir in . .. /var/crash /cores /var/lib/systemd/coredump /tmp; do
    c=$(ls -t "$dir"/core.integration-* 2>/dev/null | head -1)
    [ -n "$c" ] && core="$c" && break || true
  done
  bin=$(ls -t target/*/deps/integration-* 2>/dev/null | head -1 || true)
  # If test runs under workspace path, widen further:
  shopt -s globstar nullglob
  [ -z "$bin" ] && bin=$(ls -t **/target/*/deps/integration-* 2>/dev/null \\
    | head -1 || true)
  if [ -n "$core" ] && [ -n "$bin" ]; then
    echo "[diagnostics] Found core: $core, binary: $bin" | tee -a "$log_file"
    sudo gdb -batch -q "$bin" "$core" \\
      -ex "set pagination off" \\
      -ex "thread apply all bt full" \\
      -ex "info threads" > "$core_bt_file" 2>&1 || true
  else
    echo "[diagnostics] No core/bin found for symbolization" | tee -a "$log_file"
  fi
fi

# Check artifact files before exit to help with debugging
if [ -f "$log_file" ]; then
  echo "[artifacts] $PWD/$log_file size=$(stat -c%s "$log_file" 2>/dev/null || echo -1)"
else
  echo "[artifacts] log_file missing: $PWD/$log_file"
fi
if [ -f "$live_bt_file" ]; then
  echo "[artifacts] $PWD/$live_bt_file size=$(stat -c%s "$live_bt_file" 2>/dev/null \\
    || echo -1)"
else
  echo "[artifacts] live_bt_file missing: $PWD/$live_bt_file"
fi
if [ -f "$core_bt_file" ]; then
  echo "[artifacts] $PWD/$core_bt_file size=$(stat -c%s "$core_bt_file" 2>/dev/null \\
    || echo -1)"
else
  echo "[artifacts] core_bt_file missing: $PWD/$core_bt_file"
fi

exit $ec
'"""

        # Best-effort install gdb if not available
        try:
            self.node.execute(
                "bash -lc 'command -v gdb || "
                "(sudo dnf -y install gdb || sudo tdnf -y install gdb || "
                "sudo apt-get -y install gdb || true)'",
                shell=True,
                sudo=False,
                timeout=600,
            )
        except Exception:
            # Ignore if gdb installation fails
            pass

        result = self.node.execute(
            full_cmd,
            timeout=timeout,
            shell=True,
            cwd=self.repo_root,
            update_envs=enhanced_env_vars,
        )

        return result

    def _copy_back_artifacts(self, log_path: Path, test_name: str) -> None:
        """
        Copy diagnostic artifacts from the VM back to the test's artifact folder.
        """
        artifacts = [
            f"{test_name}.log",
            f"{test_name}_live_bt.txt",
            f"{test_name}_core_bt.txt",
        ]
        for name in artifacts:
            remote = self.repo_root / name  # where the script wrote them on the VM
            try:
                # avoid overwriting prior attempts (attempt2, attempt3, …)
                dest = log_path / name
                if dest.exists():
                    base = dest.with_suffix("") if dest.suffix else dest
                    suf = dest.suffix
                    n = 2
                    new_dest = Path(f"{base}.attempt{n}{suf}")
                    while new_dest.exists():
                        n += 1
                        new_dest = Path(f"{base}.attempt{n}{suf}")
                    dest = new_dest
                self.node.shell.copy_back(remote, dest)
                self._log.debug(f"Successfully copied back artifact: {name}")
            except Exception as e:
                self._log.debug(f"copy_back skipped for {remote}: {e}")

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        tool_path = self.get_tool_path(use_global=True)
        self.repo_root = tool_path / "cloud-hypervisor"
        self.cmd_path = self.repo_root / "scripts" / "dev_cli.sh"

    def _install(self) -> bool:
        git = self.node.tools[Git]
        clone_path = self.get_tool_path(use_global=True)
        if self.use_ms_clh_repo:
            git.clone(
                self.ms_clh_repo,
                clone_path,
                auth_token=self.ms_access_token,
            )
            self.env_vars["GUEST_VM_TYPE"] = self.clh_guest_vm_type
            if self.use_ms_guest_kernel:
                self.env_vars["USE_MS_GUEST_KERNEL"] = self.use_ms_guest_kernel
            if self.use_ms_hypervisor_fw:
                self.env_vars["USE_MS_HV_FW"] = self.use_ms_hypervisor_fw
            if self.use_ms_ovmf_fw:
                self.env_vars["USE_MS_OVMF_FW"] = self.use_ms_ovmf_fw
            if self.use_ms_bz_image:
                self.env_vars["USE_MS_BZ_IMAGE"] = self.use_ms_bz_image

            if self.use_pmem:
                self.env_vars["USE_DATADISK"] = self.use_pmem
            elif self.use_datadisk:
                self.env_vars["USE_DATADISK"] = self.use_datadisk
            if self.disable_disk_cache:
                self.env_vars["DISABLE_DATADISK_CACHING"] = self.disable_disk_cache
        else:
            git.clone(self.upstream_repo, clone_path)

        if isinstance(self.node.os, CBLMariner):
            docker_config_dir = "/etc/docker/"

            docker_config: Dict[str, Any] = {}
            docker_config["default-ulimits"] = {}
            nofiles: Dict[str, Any] = {"Hard": 65535, "Name": "nofile", "Soft": 65535}
            docker_config["default-ulimits"]["nofile"] = nofiles

            ls = self.node.tools[Ls]
            if not ls.path_exists(path=docker_config_dir, sudo=True):
                self.node.tools[Mkdir].create_directory(
                    path=docker_config_dir,
                    sudo=True,
                )

            node_info = self.node.get_information()
            distro = node_info.get("distro_version", "")
            if distro == "Microsoft Azure Linux 3.0":
                docker_config["userland-proxy"] = False

            daemon_json = json.dumps(docker_config).replace('"', '\\"')
            daemon_json_file = PurePath(f"{docker_config_dir}/daemon.json")
            self.node.tools[Echo].write_to_file(
                daemon_json, daemon_json_file, sudo=True
            )

        self.node.execute("groupadd -f docker", expected_exit_code=0)
        username = self.node.tools[Whoami].get_username()
        res = self.node.execute("getent group docker", expected_exit_code=0)
        # if current user is not in docker group
        if username not in res.stdout:
            self.node.execute(f"usermod -a -G docker {username}", sudo=True)
            # reboot for group membership change to take effect
            self.node.reboot(time_out=900)

        self.node.tools[Docker].start()

        return self._check_exists()

    def _list_subtests(self, hypervisor: str, test_type: str) -> List[str]:
        cmd_args = f"tests --hypervisor {hypervisor} --{test_type} -- -- --list"
        # Use enhanced environment variables for consistency
        enhanced_env_vars = self.env_vars.copy()
        enhanced_env_vars.update(
            {
                "RUST_BACKTRACE": "full",
                "RUST_LIB_BACKTRACE": "1",
                "RUST_LOG": os.environ.get("RUST_LOG", "debug"),
            }
        )
        result = self.run(
            cmd_args,
            timeout=self.CMD_TIME_OUT,
            force_run=True,
            cwd=self.repo_root,
            no_info_log=False,
            shell=True,
            update_envs=enhanced_env_vars,
        )
        # e.g. "integration::test_vfio: test"
        matches = re.findall(r"^(.*::.*): test", result.stdout, re.M)
        self._log.debug(f"Subtests list: {matches}")
        return matches

    def _extract_test_results(
        self, output: str, log_path: Path, subtests: Set[str]
    ) -> List[CloudHypervisorTestResult]:
        results: List[CloudHypervisorTestResult] = []
        subtest_status: Dict[str, TestStatus] = {t: TestStatus.QUEUED for t in subtests}

        # Example output:
        # test common_parallel::test_snapshot_restore_basic ... ok
        # test common_parallel::test_virtio_balloon_deflate_on_oom ... FAILED

        pattern = re.compile(r"test (?P<test_name>[^\s]+) \.{3} (?P<status>\w+)")
        test_results = find_groups_in_lines(
            lines=output,
            pattern=pattern,
        )

        for test_result in test_results:
            test_status = test_result["status"].strip().lower()
            test_name = test_result["test_name"].strip().lower()

            if test_status == "started":
                status = TestStatus.RUNNING
            elif test_status == "ok":
                status = TestStatus.PASSED
            elif test_status == "failed":
                status = TestStatus.FAILED
            elif test_status == "ignored":
                status = TestStatus.SKIPPED
            else:
                # Default to FAILED for unknown status
                status = TestStatus.FAILED

            subtest_status[test_name] = status

        messages = {
            TestStatus.QUEUED: "Subtest did not start",
            TestStatus.RUNNING: "Subtest failed to finish - timed out",
        }
        for subtest in subtests:
            status = subtest_status[subtest]
            message = messages.get(status, "")

            if status == TestStatus.RUNNING:
                # Sub-test started running but didn't finish within the stipulated time.
                # It should be treated as a failure.
                status = TestStatus.FAILED

            results.append(
                CloudHypervisorTestResult(
                    name=subtest,
                    status=status,
                    message=message,
                )
            )

        return results

    def _list_perf_metrics_tests(self, hypervisor: str = "kvm") -> Set[str]:
        tests_list = []
        result = self.run(
            f"tests --hypervisor {hypervisor} --metrics -- -- --list-tests",
            timeout=self.PERF_CMD_TIME_OUT,
            force_run=True,
            cwd=self.repo_root,
            shell=True,
            expected_exit_code=0,
            update_envs=self.env_vars,
        )

        stdout = result.stdout

        # Ex. String for below regex
        # "boot_time_ms" (test_timeout=2s,test_iterations=10)
        # "virtio_net_throughput_single_queue_rx_gbps" (test_timeout = 10s, test_iterations = 5, num_queues = 2, queue_size = 256, rx = true, bandwidth = true) # noqa: E501
        # "block_multi_queue_random_write_IOPS" (test_timeout = 10s, test_iterations = 5, num_queues = 2, queue_size = 128, fio_ops = randwrite, bandwidth = false) # noqa: E501
        # "block_multi_queue_random_read_IOPS" (test_timeout = 10s, test_iterations = 5, num_queues = 2, queue_size = 128, fio_ops = randread, bandwidth = false) # noqa: E501

        regex = '\\"(.*)\\"(.*)test_timeout(.*), test_iterations(.*)\\)'

        pattern = re.compile(regex)
        tests_list = [match[0] for match in pattern.findall(stdout)]

        self._log.debug(f"Testcases found: {tests_list}")
        return set(tests_list)

    def _process_perf_metric_test_result(self, output: str) -> str:
        # Sample Output
        # "git_human_readable": "v27.0",
        # "git_revision": "2ba6a9bfcfd79629aecf77504fa554ab821d138e",
        # "git_commit_date": "Thu Sep 29 17:56:21 2022 +0100",
        # "date": "Wed Oct 12 03:51:38 UTC 2022",
        # "results": [
        #     {
        #     "name": "block_multi_queue_read_MiBps",
        #     "mean": 158.64382311768824,
        #     "std_dev": 7.685502103050337,
        #     "max": 173.9743994350565,
        #     "min": 154.10646435356466
        #     }
        # ]
        # }
        # real    1m39.856s
        # user    0m6.376s
        # sys     2m32.973s
        # + RES=0
        # + exit 0

        output = output.replace("\n", "")
        regex = '\\"results\\"\\: (.*?)\\]'
        result = re.search(regex, output)
        if result:
            return result.group(0)
        return ""

    def _save_kernel_logs(self, log_path: Path) -> None:
        # Use serial console if available. Serial console logs can be obtained
        # even if the node goes down (hung, panicked etc.). Whereas, dmesg
        # can only be used if node is up and LISA is able to connect via SSH.
        if self.node.features.is_supported(SerialConsole):
            serial_console = self.node.features[SerialConsole]
            serial_console.get_console_log(log_path, force_run=True)
        else:
            dmesg_str = self.node.tools[Dmesg].get_output(force_run=True)
            dmesg_path = log_path / "dmesg"
            with open(str(dmesg_path), "w", encoding="utf-8") as f:
                f.write(dmesg_str)

    def _configure_vdpa_devices(self, node: Node) -> None:
        # Load the VDPA kernel modules
        node.tools[Modprobe].load("vdpa")
        node.tools[Modprobe].load("vhost_vdpa")
        node.tools[Modprobe].load("vdpa_sim")
        node.tools[Modprobe].load("vdpa_sim_blk")
        node.tools[Modprobe].load("vdpa_sim_net")

        # Device Config
        device_config = [
            {
                "dev_name": "vdpa-blk0",
                "mgmtdev_name": "vdpasim_blk",
                "device_path": "/dev/vhost-vdpa-0",
                "permission": "660",
            },
            {
                "dev_name": "vdpa-blk1",
                "mgmtdev_name": "vdpasim_blk",
                "device_path": "/dev/vhost-vdpa-1",
                "permission": "660",
            },
            {
                "dev_name": "vdpa-blk2",
                "mgmtdev_name": "vdpasim_net",
                "device_path": "/dev/vhost-vdpa-2",
                "permission": "660",
            },
        ]

        # Create VDPA Devices
        user = node.tools[Whoami].get_username()
        for device in device_config:
            dev_name = device["dev_name"]
            mgmtdev_name = device["mgmtdev_name"]
            device_path = device["device_path"]
            permission = device["permission"]

            node.execute(
                cmd=f"vdpa dev add name {dev_name} mgmtdev {mgmtdev_name}",
                sudo=True,
                shell=True,
            )
            node.tools[Chown].change_owner(file=PurePath(device_path), user=user)
            node.tools[Chmod].chmod(path=device_path, permission=permission, sudo=True)

    def _get_pmem_for_block_tests(self) -> str:
        lsblk = self.node.tools[Lsblk]
        sed = self.node.tools[Sed]
        cat = self.node.tools[Cat]

        os_major_version = int(self.node.os.information.version.major)
        if isinstance(self.node.os, CBLMariner) and os_major_version == 2:
            grub_file = "/boot/mariner-mshv.cfg"
            match_line = "mariner_cmdline_mshv="
            regexp = "$"
            replacement = f" {self.pmem_config} "
        else:
            grub_file = "/etc/default/grub"
            match_line = "GRUB_CMDLINE_LINUX="
            regexp = '"$'
            replacement = f' {self.pmem_config} "'
        cat.read(file=grub_file, sudo=True, force_run=True)
        grub_cmdline = cat.read_with_filter(
            file=grub_file,
            grep_string=match_line,
            sudo=True,
        )
        if self.pmem_config not in grub_cmdline:
            sed.substitute(
                file=grub_file,
                match_lines=f"^{match_line}",
                regexp=regexp,
                replacement=replacement,
                sudo=True,
            )
            cat.read(file=grub_file, sudo=True, force_run=True)

        if isinstance(self.node.os, CBLMariner):
            if os_major_version != 2:
                self.node.execute(
                    "grub2-mkconfig -o /boot/grub2/grub.cfg", sudo=True, shell=True
                )
        elif isinstance(self.node.os, Ubuntu):
            self.node.execute("update-grub", sudo=True, shell=True)
        else:
            raise UnsupportedDistroException(
                self.node.os,
                "pmem for CH tests is supported only on Ubuntu and CBLMariner",
            )

        lsblk.run(force_run=True)
        self.node.reboot(time_out=900)
        lsblk.run(force_run=True)

        return "/dev/pmem0"

    def _get_data_disk_for_block_tests(self) -> str:
        datadisk_name = ""
        lsblk = self.node.tools[Lsblk]
        disks = lsblk.get_disks()
        # get the first unmounted disk (data disk)
        for disk in disks:
            if disk.is_mounted:
                continue
            if disk.name.startswith("sd"):
                datadisk_name = disk.device_name
                break
        # running lsblk once again, just for human readable logs
        lsblk.run()
        if not datadisk_name:
            raise LisaException("No unmounted data disk (/dev/sdX) found")
        return datadisk_name

    def _set_block_size_env_var(self, testcase: str) -> None:
        block_size_env_var = "PERF_BLOCK_SIZE_KB"
        if block_size_env_var in self.env_vars:
            del self.env_vars[block_size_env_var]
        if "block" in testcase:
            block_size = ""
            if "MiBps" in testcase:
                block_size = self.mibps_block_size_kb
            elif "IOPS" in testcase:
                block_size = self.iops_block_size_kb

            if block_size:
                self.env_vars[block_size_env_var] = block_size

    def _record_iteration_in_tracker(
        self,
        tracker: Any,  # NumaRuntimeTracker
        metrics: str,
        result: ExecutableResult,
        testcase: str,
        log_path: Path,
    ) -> None:
        """
        TEMPORARY: Record iteration in runtime tracker.

        Parses metrics output and records the value in the tracker.
        This method will be removed after Phase 3 validation.
        """
        try:
            # Parse metrics JSON to extract value
            # metrics format: "results": [{"name": "...", "mean": X, ...}]
            metrics_json = "{" + metrics + "}"
            data = json.loads(metrics_json)

            if "results" in data and len(data["results"]) > 0:
                test_result = data["results"][0]
                value = test_result.get("mean", 0)

                # Determine unit from test name
                unit = "unknown"
                if (
                    "_MiBps" in testcase
                    or "_throughput_" in testcase
                    or "_bw_" in testcase
                ):
                    unit = "MiB/s"
                elif "_Gbps" in testcase or "_gbps" in testcase:
                    unit = "Gbps"
                elif "_IOPS" in testcase:
                    unit = "IOPS"
                elif "_ms" in testcase:
                    unit = "ms"
                elif "_us" in testcase:
                    unit = "μs"

                # Extract duration from result if available
                duration = 0.0
                if result and hasattr(result, "elapsed"):
                    duration = result.elapsed

                # Record iteration (metadata stored in test_result for reference)
                tracker.add_iteration(value=value, unit=unit, duration_sec=duration)

                self._log.debug(
                    f"Recorded iteration: {value} {unit} " f"(duration: {duration}s)"
                    if duration
                    else ""
                )

        except Exception as e:
            self._log.warning(f"Failed to record iteration in tracker: {e}")


def extract_jsons(input_string: str) -> List[Any]:
    json_results: List[Any] = []
    start_index = input_string.find("{")
    search_index = start_index
    while start_index != -1:
        end_index = input_string.find("}", search_index) + 1
        if end_index == 0:
            start_index = input_string.find("{", start_index + 1)
            search_index = start_index
            continue
        json_string = input_string[start_index:end_index]
        try:
            result = json.loads(json_string)
            json_results.append(result)
            start_index = input_string.find("{", end_index)
            search_index = start_index
        except json.decoder.JSONDecodeError:
            search_index = end_index
    return json_results
