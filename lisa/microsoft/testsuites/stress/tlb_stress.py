# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, cast

from lisa.base_tools import Cat
from lisa.executable import Tool
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.testsuite import TestResult
from lisa.tools import Chmod, Dmesg, Echo, Mkdir, Perf, StressNg
from lisa.util import LisaException, UnsupportedDistroException
from lisa.util.process import ExecutableResult

if TYPE_CHECKING:
    from lisa.node import Node


@dataclass
class PerformanceMetrics:
    """Performance metrics for TLB stress testing"""

    # Host metrics
    dtlb_load_misses_per_sec: float = 0.0
    itlb_load_misses_per_sec: float = 0.0
    context_switches_per_sec: float = 0.0
    tlb_flush_events_per_sec: float = 0.0

    # IPI/Interrupt metrics
    resched_ipis_delta: int = 0
    call_function_ipis_delta: int = 0

    # Guest performance metrics
    throughput_ops_per_sec: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    steal_time_percent: float = 0.0

    # Timing
    measurement_duration: float = 0.0
    ipi_measurement_duration: float = 0.0
    perf_event_rates: Dict[str, float] = field(default_factory=dict)
    ipi_deltas: Dict[str, int] = field(default_factory=dict)


@dataclass
class PerformanceThresholds:
    """Thresholds for performance degradation detection"""

    # Failure thresholds
    guest_throughput_degradation_percent: float = 15.0  # >15% drop = fail
    guest_p95_latency_increase_percent: float = 25.0  # >25% increase = fail
    guest_steal_time_increase_points: float = 3.0  # >3% absolute increase = fail

    # Warning thresholds
    host_dtlb_misses_increase_percent: float = 30.0  # >30% increase = warn
    host_ipis_increase_percent: float = 20.0  # >20% increase = warn

    # Monitoring window
    perf_measurement_duration: int = 45  # 45 second windows


@dataclass
class SystemMetricsSnapshot:
    """Lightweight system state snapshot for regression checks"""

    # Performance counters from perf (if available)
    dtlb_load_misses: float = 0.0
    itlb_load_misses: float = 0.0
    context_switches: float = 0.0
    cpu_migrations: float = 0.0

    # All attributes from PerformanceMetrics to ensure compatibility
    dtlb_load_misses_per_sec: float = 0.0
    itlb_load_misses_per_sec: float = 0.0
    context_switches_per_sec: float = 0.0
    tlb_flush_events_per_sec: float = 0.0

    # IPI/Interrupt metrics
    resched_ipis_delta: int = 0
    call_function_ipis_delta: int = 0

    # Guest performance metrics
    throughput_ops_per_sec: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    steal_time_percent: float = 0.0

    # Timing
    measurement_duration: float = 0.0

    # System state
    perf_available: bool = False
    interrupts_snapshot: str = ""
    telemetry_path: str = ""


class TlbStress(Tool):
    """
    TLB stress testing tool with performance monitoring capabilities.

    Provides core functionality for TLB stress testing including:
    - Custom C program deployment and execution
    - Performance metric collection (dTLB misses, steal time, etc.)
    - Environment detection (guest vs host)
    - Threshold-based degradation analysis

    Measurements require successful perf acquisition and numeric selected counters.
    Requested NUMA/THP setup is checked, and the original THP mode is restored.
    """

    # Detection - absolute paths and consistent naming
    _bin = "/usr/local/bin/tlbstress"
    _work = "/opt/tlb_flush"

    def __init__(self, node: "Node", *args: Any, **kwargs: Any) -> None:
        super().__init__(node, *args, **kwargs)
        self._is_guest_environment: Optional[bool] = None

    @property
    def command(self) -> str:
        return self._bin

    @property
    def can_install(self) -> bool:
        return True

    def _check_exists(self) -> bool:
        result = self.node.execute(
            f"test -x {self._bin}", shell=True, no_error_log=True
        )
        exists = result.exit_code == 0

        return exists

    def _probe_perf_events(self) -> Dict[str, bool]:
        """Probe which perf events are supported on this system"""
        event_support = {}
        perf_command = self.node.tools[Perf].command

        # Test events to probe
        events_to_test = [
            "dTLB-load-misses",
            "iTLB-load-misses",
            "context-switches",
            "cpu-migrations",
            "page-faults",
            "cycles",
            "instructions",
            "cache-misses",
        ]

        for event in events_to_test:
            result = self.node.execute(
                f"{perf_command} stat -e {event} -- /bin/true",
                sudo=True,
                no_error_log=True,
                timeout=10,
                update_envs={"LC_ALL": "C"},
            )
            output = f"{result.stdout}\n{result.stderr}"
            supported = (
                result.exit_code == 0
                and not result.is_timeout
                and "not supported" not in output.lower()
                and "not counted" not in output.lower()
            )
            event_support[event] = supported
            if not supported:
                self._log.debug(
                    f"perf event {event} unavailable (exit {result.exit_code}): "
                    f"{output}"
                )

        return event_support

    def _get_fallback_events(self, event_support: Dict[str, bool]) -> str:
        """Get fallback event list based on what's supported"""
        # Always include generic software events
        base_events = []

        # Add supported hardware events
        if event_support.get("context-switches", False):
            base_events.append("context-switches")
        if event_support.get("cpu-migrations", False):
            base_events.append("cpu-migrations")
        if event_support.get("page-faults", False):
            base_events.append("page-faults")

        # Add PMU events if supported
        if event_support.get("dTLB-load-misses", False):
            base_events.append("dTLB-load-misses")
        if event_support.get("iTLB-load-misses", False):
            base_events.append("iTLB-load-misses")

        if not base_events:
            raise LisaException(
                "No usable perf events for TLB measurements. Check the perf "
                "installation and permissions in the event probe output."
            )

        return ",".join(base_events)

    def _install_deps(self) -> None:
        """Install build dependencies for supported distributions only"""
        from lisa.operating_system import CBLMariner, Debian

        if isinstance(self.node.os, Debian):
            self._install_debian_deps()
        elif isinstance(self.node.os, CBLMariner):
            self._install_azurelinux_deps()
        else:
            # Raise UnsupportedDistroException for unsupported distributions
            # Test cases will catch this and convert to SkippedException
            raise UnsupportedDistroException(
                self.node.os,
                "TLB stress test only supports Ubuntu (Debian) and "
                "Azure Linux (CBL Mariner) distributions.",
            )

    def _install_debian_deps(self) -> None:
        """Install dependencies for Debian/Ubuntu systems"""
        from lisa.operating_system import Ubuntu

        packages = [
            "build-essential",
            "libc6-dev",
            "linux-headers-generic",
            "stress-ng",
            "numactl",
        ]
        if isinstance(self.node.os, Ubuntu):
            packages.append("linux-tools-generic")

        self.node.os.install_packages(packages)  # type: ignore

    def _install_azurelinux_deps(self) -> None:
        """Install dependencies for Azure Linux/CBL Mariner systems"""
        # Install essential packages first
        essential_packages = ["gcc", "make", "glibc-devel", "binutils"]
        self.node.os.install_packages(essential_packages)  # type: ignore

        # Try optional packages (best-effort)
        self._try_install_package("glibc-headers")

        # Try kernel headers - Azure Linux may have either package name
        if not self._try_install_package("kernel-headers"):
            if not self._try_install_package("kernel-devel"):
                self._log.debug("No kernel headers package found")

        # Try additional required packages
        self._install_additional_packages()

    def _try_install_package(self, package: str) -> bool:
        """
        Try to install a package on a best-effort basis.

        Returns:
            True if installation succeeded, False otherwise
        """
        try:
            self.node.os.install_packages([package])  # type: ignore
            return True
        except Exception:
            return False

    def _install_additional_packages(self) -> None:
        """
        Install additional required packages that may not be available in all repos.
        These packages are needed for full test functionality. Installation
        is attempted on a best-effort basis since package names may vary by
        distribution.
        """
        required_packages = ["gcc-c++", "stress-ng", "numactl", "perf"]
        for pkg in required_packages:
            try:
                self.node.os.install_packages([pkg])  # type: ignore
            except Exception:
                self._log.info(
                    f"Package {pkg} not available in this distribution - "
                    "some functionality may be limited"
                )

    def _verify_build_tools(self) -> None:
        """Verify that essential build tools are available"""
        essential_tools = ["gcc", "make"]
        missing_tools = []

        for tool in essential_tools:
            result = self.node.execute(f"command -v {tool}", no_error_log=True)
            if result.exit_code != 0:
                missing_tools.append(tool)

        if missing_tools:
            raise LisaException(
                f"Essential build tools missing: {', '.join(missing_tools)}"
            )

        # Verify C headers are available (optional for user-space programs)
        header_test = self.node.execute(
            "echo '#include <stdio.h>' | gcc -x c - -E -o /dev/null",
            sudo=True,
            no_error_log=True,
        )
        if header_test.exit_code != 0:
            self._log.info(
                "C standard library headers (stdio.h) not available - "
                "some advanced features may not work"
            )
            # Don't fail hard - many user-space programs can compile without
            # full headers

    def install(self) -> bool:
        """Deploy TLB stress program to target nodes with bulletproof installation"""
        # Install build dependencies first
        self._install_deps()

        self._deploy_tlb_program()

        # Verify installation was successful
        if not self._check_exists():
            raise LisaException(
                f"TLB stress installation failed - binary not found at {self._bin}"
            )

        return True

    def detect_environment_type(self) -> bool:
        """
        Detect if running in guest (VM) or host (bare metal) environment.
        Uses LISA's built-in node hierarchy for simple detection.

        Returns:
            True if guest environment, False if host environment
        """
        if self._is_guest_environment is not None:
            return self._is_guest_environment

        # Use LISA's built-in guest/host detection via node.parent
        if self.node.parent is not None:
            self._is_guest_environment = True
            return True

        # Alternative: Check if node is GuestNode instance
        from lisa.node import GuestNode

        if isinstance(self.node, GuestNode):
            self._is_guest_environment = True
            return True

        # Fallback: Check for hypervisor flag in /proc/cpuinfo as secondary detection
        try:
            cat = self.node.tools[Cat]
            cpuinfo = cat.read("/proc/cpuinfo")
            if "hypervisor" in cpuinfo.lower():
                self._is_guest_environment = True
                return True
        except Exception:
            pass

        # Default to host environment
        self._is_guest_environment = False
        return False

    def get_environment_specific_thresholds(
        self, is_guest: bool
    ) -> PerformanceThresholds:
        """
        Get performance thresholds adjusted for environment type.

        Args:
            is_guest: True if guest environment, False if host

        Returns:
            PerformanceThresholds adjusted for environment
        """
        thresholds = PerformanceThresholds()

        if is_guest:
            # Guest environment - more lenient on host metrics, stricter
            # on guest metrics
            thresholds.guest_throughput_degradation_percent = 15.0  # Stricter
            thresholds.guest_p95_latency_increase_percent = 25.0  # Stricter
            thresholds.guest_steal_time_increase_points = 3.0  # Guest-specific
            thresholds.host_dtlb_misses_increase_percent = (
                50.0  # More lenient (virtualized)
            )
            thresholds.host_ipis_increase_percent = 40.0  # More lenient (virtualized)
        else:
            # Host environment - stricter on host metrics, ignore guest-specific metrics
            thresholds.guest_throughput_degradation_percent = (
                20.0  # Slightly more lenient
            )
            thresholds.guest_p95_latency_increase_percent = (
                30.0  # Slightly more lenient
            )
            thresholds.guest_steal_time_increase_points = 999.0  # Effectively disabled
            thresholds.host_dtlb_misses_increase_percent = 25.0  # Stricter (bare metal)
            thresholds.host_ipis_increase_percent = 15.0  # Stricter (bare metal)

        return thresholds

    def capture_performance_baseline(self) -> PerformanceMetrics:
        """Capture validated counters and fresh interval samples over one window."""
        duration = PerformanceThresholds().perf_measurement_duration
        events = self._get_fallback_events(self._probe_perf_events())
        interrupts_sample_start_time = time.monotonic()
        interrupts_before = self._get_proc_interrupts()
        cpu_before = self._get_cpu_times() if self.detect_environment_type() else None
        perf_command = self.node.tools[Perf].command
        perf_result = self.node.execute(
            f"{perf_command} stat -a -e {events} -- sleep {duration}",
            sudo=True,
            timeout=duration + 30,
            update_envs={"LC_ALL": "C"},
        )
        return self._finish_performance_capture(
            perf_result,
            events,
            duration,
            interrupts_before,
            cpu_before,
            interrupts_sample_start_time,
        )

    def _finish_performance_capture(
        self,
        result: ExecutableResult,
        events: str,
        duration: int,
        interrupts_before: Dict[str, int],
        cpu_before: Optional[Tuple[int, int]],
        interrupts_sample_start_time: float,
    ) -> PerformanceMetrics:
        output = f"{result.stdout}\n{result.stderr}"
        result.assert_exit_code(message=f"TLB perf measurement failed:\n{output}")
        perf_duration = self._parse_perf_stat_duration(output)
        if (
            result.is_timeout
            or not math.isfinite(perf_duration)
            or perf_duration < duration
        ):
            raise LisaException(
                f"Invalid TLB perf measurement duration: {perf_duration}"
            )
        interrupts_after = self._get_proc_interrupts()
        ipi_measurement_duration = time.monotonic() - interrupts_sample_start_time
        rates = {
            event: self._parse_perf_stat_rate(output, event, perf_duration)
            for event in events.split(",")
        }
        if interrupts_before.keys() != interrupts_after.keys():
            raise LisaException("Available IPI counters changed during TLB measurement")
        ipi_deltas = {
            name: self._calculate_interrupt_delta(
                interrupts_before, interrupts_after, name
            )
            for name in interrupts_before
        }
        metrics = PerformanceMetrics(
            measurement_duration=perf_duration,
            ipi_measurement_duration=ipi_measurement_duration,
            perf_event_rates=rates,
            ipi_deltas=ipi_deltas,
            dtlb_load_misses_per_sec=rates.get("dTLB-load-misses", 0.0),
            itlb_load_misses_per_sec=rates.get("iTLB-load-misses", 0.0),
            context_switches_per_sec=rates.get("context-switches", 0.0),
            resched_ipis_delta=ipi_deltas.get("resched", 0),
            call_function_ipis_delta=ipi_deltas.get("call_function", 0),
        )
        if cpu_before is not None:
            total_after, steal_after = self._get_cpu_times()
            total_delta = total_after - cpu_before[0]
            steal_delta = steal_after - cpu_before[1]
            if total_delta <= 0 or not 0 <= steal_delta <= total_delta:
                raise LisaException("Invalid CPU time deltas during TLB measurement")
            metrics.steal_time_percent = 100.0 * steal_delta / total_delta
        return metrics

    def run_stress_with_monitoring(
        self,
        duration: int,
        tlb_threads: int,
        tlb_pages: int,
        use_numa: bool = True,
        use_hugepages: bool = True,
        stress_ng_parameters: str = "",
    ) -> PerformanceMetrics:
        """
        Run TLB stress test with continuous performance monitoring.

        Args:
            duration: Test duration in seconds
            tlb_threads: Number of TLB threads
            tlb_pages: Pages per thread
            use_numa: Use NUMA interleaving (reduces false regressions)
            use_hugepages: Use hugepages (explores worst-case TLB shootdowns)
            stress_ng_parameters: Optional concurrent stress-ng workload

        Returns:
            PerformanceMetrics during stress testing
        """
        self._deploy_tlb_program()
        events = self._get_fallback_events(self._probe_perf_events())
        interrupts_sample_start_time = time.monotonic()
        interrupts_before = self._get_proc_interrupts()
        cpu_before = self._get_cpu_times() if self.detect_environment_type() else None
        perf_command = self.node.tools[Perf].command
        perf_monitor_process = self.node.execute_async(
            f"{perf_command} stat -a -e {events} -- sleep {duration}",
            sudo=True,
            update_envs={"LC_ALL": "C"},
        )
        stress_ng_process = None
        try:
            if stress_ng_parameters:
                stress_ng_process = self.node.tools[StressNg].run_async(
                    stress_ng_parameters, force_run=True
                )
            self._run_tlb_stress_program(
                duration, tlb_threads, tlb_pages, use_numa, use_hugepages
            )
            if stress_ng_process is not None:
                stress_result = stress_ng_process.wait_result(timeout=duration + 30)
                stress_result.assert_exit_code(
                    message="stress-ng failed", include_output=True
                )
                if stress_result.is_timeout:
                    raise LisaException("stress-ng timed out during TLB measurement")
            perf_result = perf_monitor_process.wait_result(timeout=duration + 30)
            return self._finish_performance_capture(
                perf_result,
                events,
                duration,
                interrupts_before,
                cpu_before,
                interrupts_sample_start_time,
            )
        finally:
            try:
                if stress_ng_process is not None and stress_ng_process.is_running():
                    stress_ng_process.kill()
            finally:
                if perf_monitor_process.is_running():
                    perf_monitor_process.kill()

    @staticmethod
    def _validate_performance_metrics(metrics: PerformanceMetrics, label: str) -> None:
        if (
            not metrics.perf_event_rates
            or metrics.measurement_duration <= 0
            or metrics.ipi_measurement_duration <= 0
        ):
            raise LisaException(f"{label} has no validated TLB perf measurement")
        values = (
            metrics.measurement_duration,
            metrics.ipi_measurement_duration,
            metrics.dtlb_load_misses_per_sec,
            metrics.itlb_load_misses_per_sec,
            metrics.context_switches_per_sec,
            metrics.tlb_flush_events_per_sec,
            metrics.resched_ipis_delta,
            metrics.call_function_ipis_delta,
            metrics.throughput_ops_per_sec,
            metrics.p95_latency_ms,
            metrics.p99_latency_ms,
            metrics.steal_time_percent,
            *metrics.perf_event_rates.values(),
            *metrics.ipi_deltas.values(),
        )
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise LisaException(f"{label} contains invalid TLB performance metrics")
        if metrics.steal_time_percent > 100:
            raise LisaException(f"{label} has an invalid steal-time percentage")

    def analyze_performance_degradation(
        self,
        baseline: PerformanceMetrics,
        stress: PerformanceMetrics,
        test_result: Optional[TestResult] = None,
        start_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Analyze performance degradation against thresholds.

        Args:
            baseline: Baseline performance metrics
            stress: Stress test performance metrics
            test_result: Optional TestResult for notifier integration
            start_time: Optional start time for time-windowed kernel health checks

        Returns:
            Dictionary with analysis results
        """
        self._validate_performance_metrics(baseline, "Baseline")
        self._validate_performance_metrics(stress, "Stress measurement")
        if baseline.perf_event_rates.keys() != stress.perf_event_rates.keys():
            raise LisaException("Perf event coverage changed between TLB windows")
        if baseline.ipi_deltas.keys() != stress.ipi_deltas.keys():
            raise LisaException("IPI counter coverage changed between TLB windows")
        analysis: Dict[str, Any] = {
            "pass": True,
            "warnings": [],
            "failures": [],
            "metrics": {},
        }

        # Get environment-specific thresholds
        is_guest = self.detect_environment_type()
        thresholds = self.get_environment_specific_thresholds(is_guest)
        comparisons = 0

        # Calculate degradation percentages
        dtlb_before = baseline.perf_event_rates.get("dTLB-load-misses", 0.0)
        if dtlb_before > 0:
            comparisons += 1
            dtlb_increase_pct = (
                (stress.perf_event_rates["dTLB-load-misses"] - dtlb_before)
                / dtlb_before
            ) * 100
            analysis["metrics"]["dtlb_increase_percent"] = dtlb_increase_pct

            if dtlb_increase_pct > thresholds.host_dtlb_misses_increase_percent:
                analysis["warnings"].append(
                    f"Host dTLB misses increased by {dtlb_increase_pct:.1f}% "
                    f"(threshold: {thresholds.host_dtlb_misses_increase_percent}%)"
                )
        else:
            analysis["warnings"].append(
                "No positive dTLB baseline; the TLB miss ratio was not evaluated."
            )

        # IPI increase analysis
        ipi_total_before = (
            sum(baseline.ipi_deltas.values()) / baseline.ipi_measurement_duration
        )
        ipi_total_stress = (
            sum(stress.ipi_deltas.values()) / stress.ipi_measurement_duration
        )

        if ipi_total_before > 0:
            comparisons += 1
            ipi_increase_pct = (
                (ipi_total_stress - ipi_total_before) / ipi_total_before
            ) * 100
            analysis["metrics"]["ipi_increase_percent"] = ipi_increase_pct

            if ipi_increase_pct > thresholds.host_ipis_increase_percent:
                analysis["warnings"].append(
                    f"Host IPIs increased by {ipi_increase_pct:.1f}% "
                    f"(threshold: {thresholds.host_ipis_increase_percent}%)"
                )
        else:
            analysis["warnings"].append(
                "No positive IPI baseline; the IPI ratio was not evaluated."
            )

        # Guest steal time analysis (only relevant for guest environments)
        if is_guest:
            comparisons += 1
            steal_time_increase = (
                stress.steal_time_percent - baseline.steal_time_percent
            )
            analysis["metrics"]["steal_time_increase"] = steal_time_increase

            if steal_time_increase > thresholds.guest_steal_time_increase_points:
                analysis["failures"].append(
                    f"Guest steal time increased by "
                    f"{steal_time_increase:.1f} percentage points "
                    f"(threshold: {thresholds.guest_steal_time_increase_points})"
                )
                analysis["pass"] = False
        if not comparisons:
            raise LisaException("No usable baseline for TLB performance comparisons")

        # Check for kernel health issues (time-windowed)
        kernel_issues = self._check_kernel_health_issues(start_time)
        if kernel_issues:
            analysis["failures"].extend(kernel_issues)
            analysis["pass"] = False

        self._log.info(
            f"Performance analysis: {'PASS' if analysis['pass'] else 'FAIL'}"
        )
        if analysis["warnings"]:
            self._log.debug(f"Warnings: {'; '.join(analysis['warnings'])}")
        if test_result:
            self._send_performance_notification(test_result, analysis)

        if analysis["failures"]:
            failure_msg = (
                f"Performance test failures: {'; '.join(analysis['failures'])}"
            )
            raise LisaException(failure_msg)

        return analysis

    def _send_performance_notification(
        self, test_result: TestResult, analysis: Dict[str, Any]
    ) -> None:
        """Send performance analysis results to notifier."""
        summary_lines = ["=== TLB Stress Performance Analysis ==="]
        if "metrics" in analysis:
            summary_lines.append("Performance Metrics:")
            for key, value in analysis["metrics"].items():
                summary_lines.append(f"  {key}: {value:.2f}")
        if analysis["warnings"]:
            summary_lines.append("Warnings:")
            for warning in analysis["warnings"]:
                summary_lines.append(f"  ⚠ {warning}")
        if analysis["failures"]:
            summary_lines.append("Failures:")
            for failure in analysis["failures"]:
                summary_lines.append(f"  ❌ {failure}")
        summary_lines.append(
            f"Overall Result: {'PASS' if analysis['pass'] else 'FAIL'}"
        )
        summary_message = "\n".join(summary_lines)

        test_status = TestStatus.PASSED if analysis["pass"] else TestStatus.FAILED
        send_sub_test_result_message(
            test_result=test_result,
            test_case_name="stress_tlb_performance",
            test_status=test_status,
            test_message=summary_message,
            other_fields={"performance_metrics": analysis.get("metrics", {})},
        )

    # === Private Helper Methods ===

    def _deploy_tlb_program(self) -> None:
        """Deploy TLB flush stress program to the target node with
        bulletproof installation"""
        from lisa.node import RemoteNode

        remote_node = cast(RemoteNode, self.node)

        # Create working directory
        self.node.tools[Mkdir].create_directory(self._work, sudo=True)
        self.node.tools[Chmod].chmod(path=self._work, permission="777", sudo=True)

        # Get the C program from the same directory
        c_program_path = Path(__file__).parent / "tlb_flush_stress.c"

        # Copy the C program to the working directory
        remote_c_path = f"{self._work}/tlb_flush_stress.c"
        # Create a temporary local path for copying
        temp_local_path = remote_node.get_working_path() / "tlb_flush_stress.c"
        remote_node.shell.copy(c_program_path, temp_local_path)

        # Move to working directory with proper permissions
        self.node.execute(f"cp {temp_local_path} {remote_c_path}", sudo=True)
        self.node.execute(f"chmod 644 {remote_c_path}", sudo=True)

        # Compile the program to the standard binary location
        compile_cmd = f"gcc -O2 -pthread -o {self._bin} {remote_c_path}"
        compile_result = self.node.execute(compile_cmd, cwd=Path(self._work), sudo=True)

        if compile_result.exit_code != 0:
            raise RuntimeError(f"Compilation failed: {compile_result.stderr}")

        # Set proper permissions on the binary
        self.node.execute(f"chmod 755 {self._bin}", sudo=True)

        # Cleanup temporary files
        self.node.execute(f"rm -f {temp_local_path}", no_error_log=True)

    def _run_tlb_stress_program(
        self,
        duration: int,
        tlb_threads: int,
        tlb_pages: int,
        use_numa: bool,
        use_hugepages: bool,
    ) -> None:
        """Execute the TLB stress program with NUMA and hugepage optimizations"""
        # Build command with flag arguments (C program expects -t -p -d -i flags)
        tlb_cmd = f"{self._bin} -t {tlb_threads} -p {tlb_pages} -d {duration}"

        use_sudo = False
        if use_numa:
            available, use_sudo = self.command_exists("numactl")
            if not available:
                raise LisaException(
                    "NUMA interleaving was requested but numactl is unavailable"
                )
            tlb_cmd = f"numactl --interleave=all {tlb_cmd}"

        original_thp_mode = self._get_thp_mode() if use_hugepages else None
        try:
            if original_thp_mode is not None and original_thp_mode != "always":
                self._set_thp_mode("always")
            result = self.node.execute(tlb_cmd, sudo=use_sudo, timeout=duration + 300)
            result.assert_exit_code(
                message=f"TLB stress failed:\n{result.stdout}\n{result.stderr}"
            )
            if result.is_timeout:
                raise LisaException("TLB stress program timed out")
        finally:
            if original_thp_mode is not None and original_thp_mode != "always":
                self._set_thp_mode(original_thp_mode)

    def _get_thp_mode(self) -> str:
        output = self.node.tools[Cat].read(
            "/sys/kernel/mm/transparent_hugepage/enabled", force_run=True
        )
        match = re.search(r"\[(always|madvise|never)\]", output)
        if not match:
            raise LisaException(f"Cannot determine the active THP mode: {output}")
        return match.group(1)

    def _set_thp_mode(self, mode: str) -> None:
        self.node.tools[Echo].write_to_file(
            mode,
            PurePosixPath("/sys/kernel/mm/transparent_hugepage/enabled"),
            sudo=True,
            ignore_error=False,
        )
        if self._get_thp_mode() != mode:
            raise LisaException(f"Failed to apply THP mode {mode}")

    def _parse_perf_stat_rate(
        self, perf_output: str, event_name: str, duration: float
    ) -> float:
        """Parse perf stat output to extract event rate per second."""
        if not math.isfinite(duration) or duration <= 0:
            raise LisaException(f"Invalid perf measurement duration: {duration}")
        pattern = (
            rf"^\s*([0-9]+|[0-9]{{1,3}}(?:,[0-9]{{3}})+)"
            rf"\s+{re.escape(event_name)}(?:\s|$)"
        )
        match = re.search(pattern, perf_output, re.MULTILINE)
        if not match:
            raise LisaException(
                f"No numeric perf counter for {event_name}:\n{perf_output}"
            )
        count = float(match.group(1).replace(",", ""))
        rate = count / duration
        if not math.isfinite(rate):
            raise LisaException(f"Invalid perf counter for {event_name}")
        return rate

    @staticmethod
    def _parse_perf_stat_duration(perf_output: str) -> float:
        """Parse the collection duration reported by perf stat."""
        match = re.search(
            r"^\s*([0-9]+(?:\.[0-9]+)?) seconds time elapsed\b",
            perf_output,
            re.MULTILINE,
        )
        if not match:
            raise LisaException(
                f"No numeric perf measurement duration:\n{perf_output}"
            )
        duration = float(match.group(1))
        if not math.isfinite(duration) or duration <= 0:
            raise LisaException(f"Invalid perf measurement duration: {duration}")
        return duration

    def _get_proc_interrupts(self) -> Dict[str, int]:
        """Get current interrupt counts from /proc/interrupts."""
        output = self.node.tools[Cat].read("/proc/interrupts", force_run=True)
        interrupts = {}
        for line in output.splitlines():
            description = line.lower()
            if "resched" in description:
                name = "resched"
            elif any(
                label in description
                for label in ("call_function", "function_call", "function call")
            ):
                name = "call_function"
            else:
                continue
            _, separator, counters = line.partition(":")
            values = []
            if separator:
                for value in counters.split():
                    if not value.isdecimal():
                        break
                    values.append(int(value))
            if not values:
                raise LisaException(f"Invalid IPI counters: {line}")
            interrupts[name] = sum(values)
        return interrupts

    def _calculate_interrupt_delta(
        self, before: Dict[str, int], after: Dict[str, int], interrupt_type: str
    ) -> int:
        """Calculate interrupt count delta."""
        if interrupt_type not in before or interrupt_type not in after:
            raise LisaException(f"Missing IPI counter: {interrupt_type}")
        delta = after[interrupt_type] - before[interrupt_type]
        if delta < 0:
            raise LisaException(f"IPI counter decreased: {interrupt_type}")
        return delta

    def _get_cpu_times(self) -> Tuple[int, int]:
        output = self.node.tools[Cat].read("/proc/stat", force_run=True)
        for line in output.splitlines():
            fields = line.split()
            if fields and fields[0] == "cpu":
                if len(fields) < 9 or not all(
                    value.isdecimal() for value in fields[1:9]
                ):
                    break
                values = [int(value) for value in fields[1:9]]
                # Guest times are already included in user/nice; do not sum twice.
                return sum(values), values[7]
        raise LisaException(f"Invalid aggregate CPU counters in /proc/stat:\n{output}")

    def _check_kernel_health_issues(
        self, start_time: Optional[str] = None
    ) -> List[str]:
        """
        Check for kernel health issues using time-windowed dmesg scanning.

        Args:
            log: Logger instance
            start_time: Unix timestamp to start scanning from (eliminates
                historical noise)

        Returns:
            List of critical kernel issues found
        """
        issues = []
        try:
            if start_time:
                # Use journalctl with time window to eliminate historical noise
                scan_cmd = (
                    f"journalctl -k --since '@{start_time}' | "
                    "grep -E -i 'oom|rcu|softlockup|watchdog|hung|stall|panic|"
                    "bug:|oops|call trace' || true"
                )
            else:
                # Fallback to LISA's built-in dmesg tool
                dmesg = self.node.tools[Dmesg]
                kernel_errors = dmesg.check_kernel_errors(
                    force_run=True, throw_error=False
                )

                if kernel_errors:
                    error_lines = kernel_errors.strip().split("\n")
                    self._log.debug(f"Found {len(error_lines)} kernel errors in dmesg")
                    return [
                        f"Kernel error: {line.strip()}"
                        for line in error_lines
                        if line.strip()
                    ]
                return []

            # Execute time-windowed scan
            result = self.node.execute(scan_cmd, timeout=30)

            if result.stdout.strip():
                error_lines = result.stdout.strip().split("\n")
                self._log.debug(
                    f"Found {len(error_lines)} kernel issues since start time"
                )

                # Add all found issues (grep already filtered for critical patterns)
                for error_line in error_lines:
                    if error_line.strip():
                        issues.append(f"Critical kernel error: {error_line.strip()}")

        except Exception as e:
            self._log.debug(f"Failed to check kernel health: {e}")

        return issues

    def _capture_current_metrics(
        self, log: Optional[str] = None
    ) -> SystemMetricsSnapshot:
        """Lightweight snapshot of system state for regression checks."""
        snapshot = SystemMetricsSnapshot()
        node = self.node

        # Try to collect perf counters (best-effort)
        perf_check = node.execute(
            "command -v perf", shell=True, sudo=True, no_error_log=True
        )
        if perf_check.exit_code == 0:
            # Use capability probing for supported events
            event_support = self._probe_perf_events()
            supported_events = self._get_fallback_events(event_support)

            # Quick snapshot with supported events (-x, for CSV output)
            r = node.execute(
                f"perf stat -a -x, -e {supported_events} -- sleep 2",
                shell=True,
                sudo=True,
                no_error_log=True,
            )
            perf_metrics = self._parse_perf_csv(r.stderr)

            # Map perf metrics to snapshot attributes
            snapshot.dtlb_load_misses = perf_metrics.get("dTLB-load-misses", 0.0)
            snapshot.itlb_load_misses = perf_metrics.get("iTLB-load-misses", 0.0)
            snapshot.context_switches = perf_metrics.get("context-switches", 0.0)
            snapshot.cpu_migrations = perf_metrics.get("cpu-migrations", 0.0)
            snapshot.perf_available = True
        else:
            snapshot.perf_available = False

        # Interrupts snapshot (useful to see IPI pressure)
        irq = node.execute(
            "cat /proc/interrupts", shell=True, sudo=True, no_error_log=True
        )
        snapshot.interrupts_snapshot = irq.stdout

        # If the runner produced a telemetry CSV, record its path
        if log:
            exists = node.execute(
                f"test -f {log}", shell=True, sudo=True, no_error_log=True
            )
            if exists.exit_code == 0:
                snapshot.telemetry_path = log

        return snapshot

    def _parse_perf_csv(self, stderr: str) -> Dict[str, float]:
        """Parse perf stat CSV output into dictionary of metrics."""
        out: Dict[str, float] = {}
        for line in (stderr or "").splitlines():
            # perf -x, produces: <value>,<unit>,<event>,...
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                val, _, name = parts[0], parts[1], parts[2]
                try:
                    out[name] = float(val.replace(" ", "").replace(",", ""))
                except Exception:
                    # ignore headers/lines without numeric values
                    pass
        return out
