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
    Lscpu,
    Mkdir,
    Modprobe,
    NumaCtl,
    Sed,
    TaskSet,
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
    # 12 Hrs of timeout for perf tests (10x runs for variance analysis) + 2400s for operations
    PERF_CASE_TIME_OUT = 43200 + 2400  # 12 hours + overhead
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

    # NUMA affinity configuration
    _numa_enabled: bool = False
    _numa_bind_prefix: str = ""
    _numa_selected_node: int = 0
    _numa_cpu_range: str = ""
    _numa_tool_name: str = "none"
    _numa_policy: str = "none"  # "strict" or "interleave"

    # IRQ locality configuration
    _irq_locality_enabled: bool = False
    _irq_locality_configured_for_suite: bool = False  # Once-per-suite flag
    _irqbalance_was_running: bool = False
    _irq_metadata: Dict[str, Any] = {}

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
        # Setup NUMA affinity for stable test results on multi-NUMA systems
        # For metrics tests, require numactl (don't fall back to taskset)
        self._setup_numa_affinity(require_numactl=True)

        # Setup IRQ locality for variance reduction in multi-queue workloads
        if self._numa_enabled and self._numa_selected_node >= 0:
            self._setup_irq_locality(self._numa_selected_node)

        try:
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
            assert_that(
                failed_testcases, f"Failed Testcases: {failed_testcases}"
            ).is_empty()

        finally:
            # Always restore IRQ locality and system state
            if self._irq_locality_enabled:
                self._restore_irq_locality()
            
            # TEMPORARY: Print final runtime tracker summaries for all tests
            self._print_final_runtime_summaries(log_path)

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
            self._log.info(
                f"  Mean: {summary.mean:.2f} {summary.unit}"
            )
            self._log.info(
                f"  CV%: {summary.cv_percent:.1f}% "
                f"({self._get_variance_quality(summary.cv_percent)})"
            )
            
            # Show baseline comparison if available
            baseline_file = log_path / f"{testcase}_baseline_runtime_summary.json"
            if baseline_file.exists():
                try:
                    comparison = tracker.compare_with_baseline(str(baseline_file))
                    if comparison:
                        self._log.info(
                            f"  vs Baseline: "
                            f"{comparison['performance_diff_percent']:+.1f}% performance, "
                            f"{comparison['variance_improvement_percent']:+.1f}% variance"
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

        # TEMPORARY: Get or create runtime tracker for this test (persists across iterations)
        tracker = None
        if NUMA_TRACKER_AVAILABLE:
            if testcase not in self._runtime_trackers:
                # First time seeing this test - create new tracker
                self._runtime_trackers[testcase] = NumaRuntimeTracker(
                    test_name=testcase
                )
                self._log.debug(f"Created new runtime tracker for {testcase}")
            tracker = self._runtime_trackers[testcase]

        # Apply test-specific NUMA policy based on test type
        self._apply_numa_policy_for_test(testcase)

        self._set_block_size_env_var(testcase)
        cmd_args = self._build_metrics_cmd_args(testcase, hypervisor, subtest_timeout)

        try:
            cmd_timeout = self._get_metrics_timeout()
            safe_tc = self._sanitize_name(testcase)
            test_name = f"ch_metrics_{safe_tc}_{hypervisor}"

            try:
                # Save NUMA metadata for A/B comparison across test runs
                self._save_numa_metadata(log_path, test_name)

                # Run with enhanced diagnostics
                # NUMA binding is applied inside the bash script wrapper
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
            # Set NUMA configuration before printing
            numa_config = {
                "numa_enabled": self._numa_enabled,
                "policy": self._numa_policy,
                "numa_node": self._numa_selected_node,
                "cross_numa_access": False,  # Would need to detect from metadata
                "irq_affinity": {
                    "enabled": self._irq_locality_enabled
                }
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

# Apply NUMA binding prefix if configured
numa_prefix="{self._numa_bind_prefix if self._numa_enabled else ''}"

# start tests, line-buffered if available, stream to log
if command -v stdbuf >/dev/null; then
  ( stdbuf -oL -eL $numa_prefix scripts/dev_cli.sh {cmd_args} | tee "$log_file" ) &
else
  ( $numa_prefix scripts/dev_cli.sh {cmd_args} | tee "$log_file" ) &
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
        import json
        
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
                if "_MiBps" in testcase or "_throughput_" in testcase or "_bw_" in testcase:
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
                if result and hasattr(result, 'elapsed'):
                    duration = result.elapsed
                
                # Record iteration (metadata stored in test_result for reference)
                tracker.add_iteration(
                    value=value,
                    unit=unit,
                    duration_sec=duration
                )
                
                self._log.debug(
                    f"Recorded iteration: {value} {unit} "
                    f"(duration: {duration}s)" if duration else ""
                )
                
        except Exception as e:
            self._log.warning(f"Failed to record iteration in tracker: {e}")

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

    def _setup_numa_affinity(self, require_numactl: bool = False) -> None:  # noqa: C901
        """
        Set up NUMA affinity for Cloud Hypervisor tests.
        This ensures both CPU and memory are allocated from the same NUMA node.

        Args:
            require_numactl: If True, fail if numactl is unavailable (for perf tests)
        """
        try:
            lscpu = self.node.tools[Lscpu]
            numa_node_count = lscpu.get_numa_node_count()

            self._log.debug(f"NUMA nodes detected={numa_node_count}")

            if numa_node_count <= 1:
                self._log.debug("NUMA binding skipped: single node system")
                return

            # Try to use numactl (required for performance testing)
            try:
                numa_tool = self.node.tools[NumaCtl]

                # Get device NUMA locality if available
                device_node = self._get_device_numa_node()

                # Get the best NUMA node (prefer device node, else most free memory)
                selected_node, cpu_range = numa_tool.get_best_numa_node(
                    preferred_node=device_node
                )

                # Default to strict binding (will be adjusted per test)
                self._numa_bind_prefix = numa_tool.bind_to_node(
                    selected_node, ""
                ).strip()
                self._numa_enabled = True
                self._numa_selected_node = selected_node
                self._numa_cpu_range = cpu_range
                self._numa_tool_name = "numactl"
                self._numa_policy = "strict"

                device_info = (
                    f" device_node={device_node}" if device_node is not None else ""
                )
                self._log.info(
                    f"NUMA enabled tool=numactl node={selected_node} "
                    f"cpus={cpu_range} policy=strict{device_info}"
                )

            except Exception as e:
                if require_numactl:
                    raise LisaException(
                        "numactl is required for performance testing but unavailable. "
                        f"Error: {e}"
                    )

                self._log.debug(f"numactl not available: {e}")
                try:
                    # Fallback to taskset for CPU affinity only (non-perf tests)
                    taskset = self.node.tools[TaskSet]

                    # Find node with most free memory for consistency
                    best_node = 0
                    max_free_memory = 0
                    for node_id in range(numa_node_count):
                        try:
                            result = self.node.execute(
                                f"cat /sys/devices/system/node/node{node_id}/meminfo",
                                shell=True,
                            )
                            if result.exit_code == 0:
                                for line in result.stdout.split("\n"):
                                    if "MemFree:" in line:
                                        free_kb = int(line.split()[3])
                                        if free_kb > max_free_memory:
                                            max_free_memory = free_kb
                                            best_node = node_id
                                        break
                        except Exception:
                            continue

                    selected_node = best_node
                    start_cpu, end_cpu = lscpu.get_cpu_range_in_numa_node(selected_node)
                    cpu_range = f"{start_cpu}-{end_cpu}"
                    self._numa_bind_prefix = f"{taskset.command} -c {cpu_range}"
                    self._numa_enabled = True
                    self._numa_selected_node = selected_node
                    self._numa_cpu_range = cpu_range
                    self._numa_tool_name = "taskset"
                    self._numa_policy = "strict"

                    self._log.info(
                        f"NUMA enabled tool=taskset node={selected_node} "
                        f"cpus={cpu_range} memory=unbound"
                    )

                except Exception as e2:
                    self._log.debug(f"NUMA binding unavailable: {e2}")

        except Exception as e:
            self._log.debug(f"NUMA setup failed: {e}")

    def _get_device_numa_node(self) -> Optional[int]:
        """
        Detect NUMA node of the primary test device (NVMe or NIC).
        Returns None if device NUMA cannot be determined.
        """
        # Check for NVMe devices (block tests)
        try:
            result = self.node.execute(
                "cat /sys/class/nvme/nvme*/device/numa_node 2>/dev/null | head -1",
                shell=True,
            )
            if result.exit_code == 0 and result.stdout.strip():
                numa_node = int(result.stdout.strip())
                if numa_node >= 0:  # -1 means no NUMA affinity
                    self._log.debug(f"Detected NVMe on NUMA node {numa_node}")
                    return numa_node
        except Exception:
            pass

        # Check for primary network interface (network tests)
        # Try to detect the interface being used for testing
        try:
            # Look for interfaces with device/numa_node (excludes loopback, virtual)
            result = self.node.execute(
                "for iface in /sys/class/net/*/device/numa_node; do "
                '[ -f "$iface" ] && cat "$iface" && break; done',
                shell=True,
            )
            if result.exit_code == 0 and result.stdout.strip():
                numa_node = int(result.stdout.strip())
                if numa_node >= 0:
                    self._log.debug(f"Detected NIC on NUMA node {numa_node}")
                    return numa_node
        except Exception:
            pass

        self._log.debug("Device NUMA node not detected, using memory-based selection")
        return None

    def _detect_workload_parallelism(self, testcase: str) -> str:
        """
        Detect workload parallelism using both runtime queue detection and name patterns.
        
        Returns:
            "multi_queue": Workload benefits from interleave policy (spreads across NUMA)
            "single_queue": Workload benefits from strict policy (stays on one node)
        """
        tc_name = str(testcase).lower()
        
        # Runtime queue detection (ground truth)
        try:
            # Check NIC queues
            nic_queues = 0
            result = self.node.execute(
                "ls -1d /sys/class/net/eth*/queues/rx-* 2>/dev/null | wc -l",
                shell=True,
                sudo=True,
            )
            if result.exit_code == 0 and result.stdout.strip().isdigit():
                nic_queues = int(result.stdout.strip())
            
            # Check NVMe queues (subtract 1 for admin queue)
            nvme_queues = 0
            result = self.node.execute(
                "grep -c 'nvme.*q' /proc/interrupts 2>/dev/null || echo 0",
                shell=True,
                sudo=True,
            )
            if result.exit_code == 0 and result.stdout.strip().isdigit():
                nvme_queues = max(0, int(result.stdout.strip()) - 1)
            
            # Multi-queue if either device has >1 queue
            if nic_queues > 1 or nvme_queues > 1:
                self._log.debug(
                    f"Multi-queue detected: nic_queues={nic_queues}, "
                    f"nvme_queues={nvme_queues}"
                )
                return "multi_queue"
        except Exception as e:
            self._log.debug(f"Runtime queue detection failed: {e}")
        
        # Fallback: Name-based pattern detection
        # Performance/stress tests likely use multiple queues
        if any(x in tc_name for x in ["perf_", "stress", "throughput", "iops", "_bw_", "_throughput_"]):
            self._log.debug(f"Multi-queue inferred from test name: {testcase}")
            return "multi_queue"
        
        # Explicit multi-queue markers
        if "multi_queue" in tc_name or "multiqueue" in tc_name:
            self._log.debug(f"Multi-queue explicit in test name: {testcase}")
            return "multi_queue"
        
        # Default: assume single-queue
        self._log.debug(f"Single-queue assumed for test: {testcase}")
        return "single_queue"

    def _apply_numa_policy_for_test(self, testcase: str) -> None:
        """
        Apply test-specific NUMA policy based on workload parallelism.

        Single-queue tests: Use strict binding (--cpunodebind=N --membind=N)
        Multi-queue tests: Use interleave policy (--interleave=all)
        """
        if not self._numa_enabled or self._numa_tool_name != "numactl":
            return

        # Dynamic detection instead of simple name matching
        workload_type = self._detect_workload_parallelism(testcase)
        is_multi_queue = (workload_type == "multi_queue")

        try:
            numa_tool = self.node.tools[NumaCtl]

            if is_multi_queue:
                # Multi-queue: use interleave for better distribution
                self._numa_bind_prefix = numa_tool.bind_interleave()
                self._numa_policy = "interleave"
                self._log.info(
                    f"NUMA policy=interleave test={testcase} "
                    f"(workload_type={workload_type})"
                )
            else:
                # Single-queue: use strict binding
                self._numa_bind_prefix = numa_tool.bind_to_node(
                    self._numa_selected_node, ""
                ).strip()
                self._numa_policy = "strict"
                self._log.debug(
                    f"NUMA policy=strict test={testcase} "
                    f"node={self._numa_selected_node} (workload_type={workload_type})"
                )
        except Exception as e:
            self._log.debug(f"Failed to apply NUMA policy for {testcase}: {e}")

    def _save_numa_metadata(self, log_path: Path, test_name: str) -> None:
        """
        Save comprehensive NUMA binding metadata to JSON for variance analysis.
        Includes configuration, runtime detection, and risk factors.
        """
        if not self._numa_enabled:
            return

        # Detect cross-NUMA access
        device_node = self._get_device_numa_node()
        cross_numa_access = (
            device_node is not None and 
            device_node >= 0 and 
            device_node != self._numa_selected_node
        )
        
        # Get runtime queue counts
        nic_queues = 0
        nvme_queues = 0
        try:
            result = self.node.execute(
                "ls -1d /sys/class/net/eth*/queues/rx-* 2>/dev/null | wc -l",
                shell=True,
                sudo=True,
            )
            if result.exit_code == 0 and result.stdout.strip().isdigit():
                nic_queues = int(result.stdout.strip())
            
            result = self.node.execute(
                "grep -c 'nvme.*q' /proc/interrupts 2>/dev/null || echo 0",
                shell=True,
                sudo=True,
            )
            if result.exit_code == 0 and result.stdout.strip().isdigit():
                nvme_queues = max(0, int(result.stdout.strip()) - 1)
        except Exception:
            pass
        
        # Get irqbalance state snapshot
        irqbalance_state = {"stopped": False, "active": False}
        try:
            result = self.node.execute(
                "systemctl is-active irqbalance 2>/dev/null || "
                "service irqbalance status 2>/dev/null | grep -q running && echo active || echo inactive",
                shell=True,
            )
            if "active" in result.stdout.lower():
                irqbalance_state["active"] = True
            irqbalance_state["stopped"] = self._irqbalance_was_running
        except Exception:
            pass
        
        # Compute configuration hash
        config_hash = self._compute_numa_config_hash()
        
        # Get configurable threshold
        try:
            numa_tool = self.node.tools[NumaCtl]
            min_memory_mb = getattr(numa_tool, 'ABSOLUTE_MIN_MEMORY_MB', 2048)
        except Exception:
            min_memory_mb = 2048
        
        numa_meta = {
            "numa_enabled": self._numa_enabled,
            "selected_node": self._numa_selected_node,
            "device_node": device_node,
            "policy": self._numa_policy,
            "cpu_range": self._numa_cpu_range,
            "tool": self._numa_tool_name,
            
            # Cross-NUMA detection
            "cross_numa_access": cross_numa_access,
            
            # Runtime queue counts
            "detected_queues": {
                "nic_rx": nic_queues,
                "nvme": nvme_queues,
            },
            
            # Workload classification
            "workload_type": self._detect_workload_parallelism(test_name),
            
            # Variance risk factors
            "variance_risk_factors": self._get_variance_risk_factors(),
            
            # IRQ locality state
            "irq_affinity": {
                "enabled": self._irq_locality_enabled,
                "irqbalance_stopped": irqbalance_state.get("stopped", False),
                "irqbalance_active": irqbalance_state.get("active", False),
                "nvme_irqs_pinned": self._irq_metadata.get("nvme_irqs_pinned", []) if self._irq_metadata else [],
                "nic_irqs_pinned": self._irq_metadata.get("nic_irqs_pinned", []) if self._irq_metadata else [],
                "cpu_mask": self._irq_metadata.get("cpu_mask", "") if self._irq_metadata else "",
                "rps_xps_configured": self._irq_metadata.get("rps_xps_configured", False) if self._irq_metadata else False,
            },
            
            # Configuration hash (for comparing runs)
            "config_hash": config_hash,
            "config_details": {
                "memory_threshold_mb": min_memory_mb,
                "policy_mode": "dynamic",  # vs "always_interleave" or "always_strict"
                "irq_locality_mode": "auto",  # vs "always" or "never"
                "prefer_device_node": True,
            },
        }

        meta_file = log_path / f"{test_name}_numa_meta.json"
        try:
            with open(meta_file, "w") as f:
                json.dump(numa_meta, f, indent=2)
            self._log.debug(f"Saved enhanced NUMA metadata to {meta_file}")
        except Exception as e:
            self._log.debug(f"Failed to save NUMA metadata: {e}")

    def _compute_numa_config_hash(self) -> str:
        """
        Compute MD5 hash of NUMA configuration for reproducibility tracking.
        Allows comparing runs to see if configuration drift explains variance changes.
        
        Returns:
            MD5 hash of configuration string
        """
        import hashlib
        
        # Include all tunable parameters that affect performance
        config_str = "|".join([
            f"numa_enabled={self._numa_enabled}",
            f"numa_tool={self._numa_tool_name}",
            f"numa_policy={self._numa_policy}",
            f"numa_node={self._numa_selected_node}",
            f"irq_locality={self._irq_locality_enabled}",
            f"irqbalance_stopped={self._irqbalance_was_running}",
        ])
        
        return hashlib.md5(config_str.encode()).hexdigest()[:16]
    
    def _get_variance_risk_factors(self) -> list:
        """
        Identify configuration patterns known to increase variance.
        Used for post-mortem analysis to correlate config with variance.
        
        Returns:
            List of risk factor strings
        """
        risks = []
        
        # Cross-NUMA device access is a major variance source
        device_node = self._get_device_numa_node()
        if (device_node is not None and
                device_node >= 0 and
                device_node != self._numa_selected_node):
            risks.append("cross_numa_device_access")
        
        # Strict policy on multi-queue workloads can underutilize resources
        if self._numa_policy == "strict":
            # Check if this might be a multi-queue workload
            try:
                result = self.node.execute(
                    "ls -1d /sys/class/net/eth*/queues/rx-* 2>/dev/null | wc -l",
                    shell=True,
                    sudo=True,
                )
                if result.exit_code == 0 and result.stdout.strip().isdigit():
                    nic_queues = int(result.stdout.strip())
                    if nic_queues > 1:
                        risks.append("strict_policy_on_multiqueue")
            except Exception:
                pass
        
        # IRQ pinning on single-queue adds overhead without benefit
        if self._irq_locality_enabled:
            try:
                result = self.node.execute(
                    "grep -c 'nvme.*q' /proc/interrupts 2>/dev/null || echo 0",
                    shell=True,
                    sudo=True,
                )
                nvme_queues = 0
                if result.exit_code == 0 and result.stdout.strip().isdigit():
                    nvme_queues = max(0, int(result.stdout.strip()) - 1)
                
                result = self.node.execute(
                    "ls -1d /sys/class/net/eth*/queues/rx-* 2>/dev/null | wc -l",
                    shell=True,
                    sudo=True,
                )
                nic_queues = 0
                if result.exit_code == 0 and result.stdout.strip().isdigit():
                    nic_queues = int(result.stdout.strip())
                
                if nic_queues <= 1 and nvme_queues <= 1:
                    risks.append("unnecessary_irq_pinning")
            except Exception:
                pass
        
        return risks

    def _cpulist_to_hex_mask(self, cpu_list: str) -> str:
        """
        Convert CPU list to hex mask for IRQ affinity.

        Args:
            cpu_list: e.g., "0-15,32-47" or "16-31"

        Returns:
            Hex mask string, e.g., "ffff,0000ffff" or "ffff0000"
        """
        # Parse CPU ranges
        cpus: Set[int] = set()
        for part in cpu_list.split(","):
            part = part.strip()
            if "-" in part:
                start, end = map(int, part.split("-"))
                cpus.update(range(start, end + 1))
            elif part.isdigit():
                cpus.add(int(part))

        if not cpus:
            raise LisaException(f"Invalid CPU list: {cpu_list}")

        # Create bitmask (each CPU is one bit)
        mask = 0
        for cpu in cpus:
            mask |= 1 << cpu

        # Convert to hex and group from the RIGHT (little-endian groups of 32 CPUs)
        # This is critical for /proc/irq/*/smp_affinity on systems with >32 CPUs
        hex_str = f"{mask:x}"

        # Pad to multiple of 8 hex digits
        pad = (-len(hex_str)) % 8
        hex_str = ("0" * pad) + hex_str

        # Split from rightmost, 8 hex chars per group (each group = 32 CPUs)
        parts = []
        for i in range(len(hex_str), 0, -8):
            parts.append(hex_str[max(0, i - 8) : i])

        return ",".join(parts)  # rightmost group = lowest CPUs

    def _get_nvme_irqs(self) -> List[int]:
        """
        Find all IRQ numbers for NVMe devices.

        Returns list of IRQ numbers.
        """
        try:
            # Method 1: Parse /proc/interrupts (most reliable)
            result = self.node.execute(
                "grep -E 'nvme[0-9]+q' /proc/interrupts | "
                "awk '{print $1}' | tr -d ':'",
                shell=True,
            )

            irqs = []
            if result.exit_code == 0 and result.stdout.strip():
                irqs = [
                    int(irq)
                    for irq in result.stdout.strip().split("\n")
                    if irq.isdigit()
                ]

            # Method 2: Fallback to MSI IRQs via sysfs (for vendor-specific drivers)
            if not irqs:
                result = self.node.execute(
                    "find /sys/class/nvme/*/device/msi_irqs/ -type f "
                    "2>/dev/null | xargs -r basename -a | sort -n",
                    shell=True,
                )
                if result.exit_code == 0 and result.stdout.strip():
                    irqs = [
                        int(irq)
                        for irq in result.stdout.strip().split("\n")
                        if irq.isdigit()
                    ]

            self._log.debug(f"Detected NVMe IRQs: {irqs}")
            return irqs

        except Exception as e:
            self._log.debug(f"Failed to get NVMe IRQs: {e}")
            return []

    def _get_nic_irqs(self, interface: str = "") -> List[int]:
        """
        Find all IRQ numbers for network interfaces.

        Args:
            interface: Network interface name (auto-detected if empty)

        Returns list of IRQ numbers.
        """
        try:
            # Auto-detect interface if not specified
            if not interface:
                result = self.node.execute(
                    "ls /sys/class/net/ | grep -E '^(eth|ens|enp|eno)' | head -1",
                    shell=True,
                )
                interface = result.stdout.strip()

            if not interface:
                self._log.debug("No network interface found")
                return []

            # Method 1: MSI IRQs (preferred)
            result = self.node.execute(
                f"find /sys/class/net/{interface}/device/msi_irqs/ -type f "
                "2>/dev/null | xargs -r basename -a | sort -n",
                shell=True,
            )

            irqs = []
            if result.exit_code == 0 and result.stdout.strip():
                irqs = [
                    int(irq)
                    for irq in result.stdout.strip().split("\n")
                    if irq.isdigit()
                ]

            # Method 2: Fallback to /proc/interrupts
            if not irqs:
                result = self.node.execute(
                    f"grep '{interface}' /proc/interrupts | "
                    "awk '{print $1}' | tr -d ':'",
                    shell=True,
                )
                if result.exit_code == 0 and result.stdout.strip():
                    irqs = [
                        int(irq)
                        for irq in result.stdout.strip().split("\n")
                        if irq.isdigit()
                    ]

            self._log.debug(f"Detected {interface} IRQs: {irqs}")
            return irqs

        except Exception as e:
            self._log.debug(f"Failed to get NIC IRQs: {e}")
            return []

    def _pin_irqs(self, irqs: List[int], cpu_mask: str) -> List[int]:
        """
        Pin a list of IRQs to specified CPU mask.

        Returns list of successfully pinned IRQs.
        """
        pinned = []

        for irq in irqs:
            try:
                # Write to smp_affinity
                self.node.execute(
                    f"echo {cpu_mask} | "
                    f"sudo tee /proc/irq/{irq}/smp_affinity > /dev/null",
                    shell=True,
                )

                # Verify it stuck
                result = self.node.execute(
                    f"cat /proc/irq/{irq}/smp_affinity", shell=True
                )

                # Normalize for comparison (remove commas and spaces)
                actual_mask = result.stdout.strip().replace(",", "").replace(" ", "")
                expected_mask = cpu_mask.replace(",", "").replace(" ", "")

                if expected_mask in actual_mask or actual_mask in expected_mask:
                    pinned.append(irq)
                    self._log.debug(f"Pinned IRQ {irq} to mask {cpu_mask}")
                else:
                    self._log.debug(
                        f"IRQ {irq} affinity verification failed "
                        f"(expected={expected_mask}, actual={actual_mask})"
                    )

            except Exception as e:
                self._log.debug(f"Failed to pin IRQ {irq}: {e}")

        return pinned

    def _stop_irqbalance(self) -> bool:
        """Stop irqbalance service to prevent dynamic IRQ rebalancing."""
        try:
            # Check if irqbalance is running
            result = self.node.execute(
                "systemctl is-active irqbalance 2>/dev/null || "
                "service irqbalance status 2>/dev/null",
                shell=True,
            )

            was_running = result.exit_code == 0

            if was_running:
                # Try systemd first, then sysvinit
                self.node.execute(
                    "sudo systemctl stop irqbalance 2>/dev/null || "
                    "sudo service irqbalance stop 2>/dev/null",
                    shell=True,
                )
                self._log.info("Stopped irqbalance service")
                self._irqbalance_was_running = True
                return True
            else:
                self._log.debug("irqbalance not running")
                self._irqbalance_was_running = False
                return False

        except Exception as e:
            self._log.debug(f"Failed to stop irqbalance: {e}")
            return False

    def _setup_rps_xps(self, cpu_mask: str) -> bool:
        """
        Configure RPS (Receive Packet Steering) and XPS (Transmit Packet Steering).
        This ensures network queue processing stays on the selected NUMA node.
        """
        try:
            # Find primary NIC
            result = self.node.execute(
                "ls /sys/class/net/ | grep -E '^(eth|ens|enp|eno)' | head -1",
                shell=True,
            )
            nic = result.stdout.strip()

            if not nic:
                self._log.debug("No NIC found for RPS/XPS configuration")
                return False

            # Configure RPS for all RX queues
            self.node.execute(
                f"for rps in /sys/class/net/{nic}/queues/rx-*/rps_cpus; do "
                f'[ -f "$rps" ] && echo {cpu_mask} | sudo tee $rps > /dev/null; '
                f"done",
                shell=True,
            )

            # Configure XPS for all TX queues
            self.node.execute(
                f"for xps in /sys/class/net/{nic}/queues/tx-*/xps_cpus; do "
                f'[ -f "$xps" ] && echo {cpu_mask} | sudo tee $xps > /dev/null; '
                f"done",
                shell=True,
            )

            # Get queue counts for logging
            rx_result = self.node.execute(
                f"ls /sys/class/net/{nic}/queues/rx-* 2>/dev/null | wc -l",
                shell=True,
            )
            rx_count = int(rx_result.stdout.strip() or "0")

            tx_result = self.node.execute(
                f"ls /sys/class/net/{nic}/queues/tx-* 2>/dev/null | wc -l",
                shell=True,
            )
            tx_count = int(tx_result.stdout.strip() or "0")

            self._log.info(
                f"Configured RPS/XPS for {nic}: rx_queues={rx_count} "
                f"tx_queues={tx_count} mask={cpu_mask}"
            )
            return True

        except Exception as e:
            self._log.debug(f"RPS/XPS configuration failed: {e}")
            return False

    def _should_apply_irq_locality(self) -> bool:
        """
        Determine if IRQ locality should be applied for current test suite.
        
        Gating conditions:
        1. Skip if already configured for this suite (once-per-suite)
        2. Skip if system has single-queue devices only (no benefit)
        
        Returns:
            True if IRQ locality should be applied, False otherwise
        """
        # Already configured for this suite?
        if self._irq_locality_configured_for_suite:
            self._log.debug("IRQ locality already configured for suite, skipping")
            return False
        
        # Runtime queue detection: skip if single-queue devices only
        try:
            # Check NIC queues
            nic_queues = 0
            result = self.node.execute(
                "ls -1d /sys/class/net/eth*/queues/rx-* 2>/dev/null | wc -l",
                shell=True,
                sudo=True,
            )
            if result.exit_code == 0 and result.stdout.strip().isdigit():
                nic_queues = int(result.stdout.strip())
            
            # Check NVMe queues (subtract 1 for admin queue)
            nvme_queues = 0
            result = self.node.execute(
                "grep -c 'nvme.*q' /proc/interrupts 2>/dev/null || echo 0",
                shell=True,
                sudo=True,
            )
            if result.exit_code == 0 and result.stdout.strip().isdigit():
                nvme_queues = max(0, int(result.stdout.strip()) - 1)
            
            # Skip if both devices are single-queue
            if nic_queues <= 1 and nvme_queues <= 1:
                self._log.info(
                    f"Skipping IRQ locality: single-queue devices detected "
                    f"(nic_queues={nic_queues}, nvme_queues={nvme_queues})"
                )
                return False
            
            self._log.debug(
                f"Multi-queue devices detected: nic_queues={nic_queues}, "
                f"nvme_queues={nvme_queues} - IRQ locality will be applied"
            )
            return True
            
        except Exception as e:
            # On detection failure, apply conservatively
            self._log.debug(f"Queue detection failed: {e}, applying IRQ locality")
            return True

    def _setup_irq_locality(self, selected_node: int) -> None:
        """
        Configure IRQ affinity for selected NUMA node (once per suite).
        Stops irqbalance and pins device IRQs to node CPUs.
        This is the #1 variance killer for multi-queue I/O and networking.
        """
        if selected_node < 0:
            self._log.debug("Invalid NUMA node, skipping IRQ locality")
            return
        
        # Check if we should apply IRQ locality
        if not self._should_apply_irq_locality():
            return

        try:
            # Get CPU mask for this node
            result = self.node.execute(
                f"cat /sys/devices/system/node/node{selected_node}/cpulist",
                shell=True,
            )
            cpu_list = result.stdout.strip()
            cpu_mask = self._cpulist_to_hex_mask(cpu_list)

            self._log.info(
                f"Setting up IRQ locality: node={selected_node} "
                f"cpus={cpu_list} mask={cpu_mask}"
            )

            # Stop irqbalance to prevent interference
            irqbalance_stopped = self._stop_irqbalance()

            # Pin NVMe IRQs
            nvme_irqs = self._get_nvme_irqs()
            nvme_pinned = self._pin_irqs(nvme_irqs, cpu_mask)

            # Pin NIC IRQs
            nic_irqs = self._get_nic_irqs()
            nic_pinned = self._pin_irqs(nic_irqs, cpu_mask)

            # Configure RPS/XPS for NICs (only if multi-queue)
            rps_xps_configured = False
            if nic_irqs:
                # Check if NIC is multi-queue before configuring RPS/XPS
                result = self.node.execute(
                    "ls -1d /sys/class/net/eth*/queues/rx-* 2>/dev/null | wc -l",
                    shell=True,
                    sudo=True,
                )
                nic_queues = 0
                if result.exit_code == 0 and result.stdout.strip().isdigit():
                    nic_queues = int(result.stdout.strip())
                
                if nic_queues > 1:
                    rps_xps_configured = self._setup_rps_xps(cpu_mask)
                    self._log.debug(f"RPS/XPS configured for multi-queue NIC ({nic_queues} queues)")
                else:
                    self._log.debug(f"Skipping RPS/XPS for single-queue NIC ({nic_queues} queue)")

            # Store metadata for logging
            self._irq_metadata = {
                "enabled": True,
                "irqbalance_stopped": irqbalance_stopped,
                "nvme_irqs_pinned": nvme_pinned,
                "nic_irqs_pinned": nic_pinned,
                "cpu_mask": cpu_mask,
                "rps_xps_configured": rps_xps_configured,
            }

            self._irq_locality_enabled = True
            self._irq_locality_configured_for_suite = True  # Mark as configured for suite

            self._log.info(
                f"IRQ locality configured for suite: nvme_irqs={len(nvme_pinned)} "
                f"nic_irqs={len(nic_pinned)} rps_xps={rps_xps_configured}"
            )

        except Exception as e:
            self._log.warning(f"IRQ locality setup failed (non-fatal): {e}")
            self._irq_metadata = {"enabled": False, "error": str(e)}
            self._irq_locality_enabled = False

    def _restore_irq_locality(self) -> None:
        """
        Restore system to default IRQ configuration.
        Called in test cleanup/finally block.
        """
        try:
            # Restore irqbalance (will automatically rebalance IRQs)
            if self._irqbalance_was_running:
                try:
                    self.node.execute(
                        "sudo systemctl start irqbalance 2>/dev/null || "
                        "sudo service irqbalance start 2>/dev/null",
                        shell=True,
                    )
                    self._log.info("Restored irqbalance service")
                except Exception as e:
                    self._log.debug(f"Failed to restore irqbalance: {e}")

            # Optional: Explicitly restore IRQ affinities to "all CPUs"
            if self._irq_locality_enabled and self._irq_metadata.get("enabled"):
                all_irqs = self._irq_metadata.get(
                    "nvme_irqs_pinned", []
                ) + self._irq_metadata.get("nic_irqs_pinned", [])

                if all_irqs:
                    # Reset to all CPUs (all f's mask)
                    result = self.node.execute(
                        "grep -c processor /proc/cpuinfo", shell=True
                    )
                    cpu_count = int(result.stdout.strip())
                    # Create mask with all bits set for cpu_count CPUs
                    all_cpus_mask = "f" * ((cpu_count + 3) // 4)

                    for irq in all_irqs:
                        try:
                            self.node.execute(
                                f"echo {all_cpus_mask} | "
                                f"sudo tee /proc/irq/{irq}/smp_affinity > /dev/null",
                                shell=True,
                            )
                        except Exception:
                            pass  # Best effort

            self._log.info("Restored default IRQ configuration")

        except Exception as e:
            self._log.debug(f"IRQ locality cleanup failed: {e}")


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
