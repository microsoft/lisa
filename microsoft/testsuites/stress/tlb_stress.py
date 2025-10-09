# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast

from lisa.base_tools import Cat
from lisa.executable import Tool
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.testsuite import TestResult
from lisa.tools import Dmesg
from lisa.util import LisaException, UnsupportedDistroException

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

    def _unlock_perf_counters(self) -> None:
        """Unlock perf counters so dTLB/iTLB/context-switch counters aren't zero"""
        try:
            # Check current setting
            result = self.node.execute(
                "cat /proc/sys/kernel/perf_event_paranoid", no_error_log=True
            )
            current_value = result.stdout.strip()

            if current_value != "-1":
                self.node.execute("sysctl -w kernel.perf_event_paranoid=-1", sudo=True)
        except Exception as e:
            self._log.debug(
                f"Failed to unlock perf counters: {e}. Will use sudo for perf commands."
            )

    def _probe_perf_events(self) -> Dict[str, bool]:
        """Probe which perf events are supported on this system"""
        event_support = {}

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
            try:
                # Quick test: perf stat -e EVENT -- /bin/true
                result = self.node.execute(
                    f"perf stat -e {event} -- /bin/true",
                    sudo=True,
                    no_error_log=True,
                    timeout=10,
                )
                # If no error and doesn't contain "<not supported>", event is supported
                supported = (
                    result.exit_code == 0
                    and "<not supported>" not in result.stderr
                    and "not supported" not in result.stderr
                )
                event_support[event] = supported
            except Exception:
                event_support[event] = False

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

        # If no events supported, use minimal set
        if not base_events:
            base_events = ["context-switches", "page-faults"]
            self._log.debug(
                "No perf events detected as supported, using minimal fallback set"
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
        packages = [
            "build-essential",
            "libc6-dev",
            "linux-headers-generic",
            "stress-ng",
            "numactl",
            "linux-tools-generic",
        ]

        self.node.os.install_packages(packages)  # type: ignore

    def _install_azurelinux_deps(self) -> None:
        """Install dependencies for Azure Linux/CBL Mariner systems"""
        # Install essential packages first
        essential_packages = ["gcc", "make", "glibc-devel"]
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
        """
        Capture baseline performance metrics before stress testing.

        Returns:
            PerformanceMetrics with baseline measurements
        """
        # Unlock perf counters for detailed TLB/context-switch monitoring
        self._unlock_perf_counters()

        thresholds = PerformanceThresholds()
        duration = thresholds.perf_measurement_duration
        baseline = PerformanceMetrics(measurement_duration=duration)

        try:
            # Probe which perf events are supported
            event_support = self._probe_perf_events()
            supported_events = self._get_fallback_events(event_support)

            # Capture host perf metrics (TLB misses, context switches)
            # Run perf stat with supported events
            perf_cmd = (
                f"perf stat -a -e {supported_events} "
                f"--timeout {duration * 1000} sleep {duration}"
            )

            perf_result = self.node.execute(perf_cmd, sudo=True, timeout=duration + 30)

            # Parse supported events with fallback
            if event_support.get("dTLB-load-misses", False):
                baseline.dtlb_load_misses_per_sec = self._parse_perf_stat_rate(
                    perf_result.stderr, "dTLB-load-misses", duration
                )
            if event_support.get("iTLB-load-misses", False):
                baseline.itlb_load_misses_per_sec = self._parse_perf_stat_rate(
                    perf_result.stderr, "iTLB-load-misses", duration
                )
            if event_support.get("context-switches", False):
                baseline.context_switches_per_sec = self._parse_perf_stat_rate(
                    perf_result.stderr, "context-switches", duration
                )

            # Capture /proc/interrupts for IPI baseline
            interrupts_before = self._get_proc_interrupts()

            # Wait and capture again for delta calculation
            time.sleep(5)  # Small sample window for IPI rate
            interrupts_after = self._get_proc_interrupts()

            baseline.resched_ipis_delta = self._calculate_interrupt_delta(
                interrupts_before, interrupts_after, "resched"
            )
            baseline.call_function_ipis_delta = self._calculate_interrupt_delta(
                interrupts_before, interrupts_after, "call_function"
            )

            # Capture guest steal time baseline
            is_guest = self.detect_environment_type()
            baseline.steal_time_percent = self._get_steal_time_percent(is_guest)

            return baseline

        except Exception as e:
            self._log.debug(f"Failed to capture complete baseline metrics: {e}")
            return baseline

    def run_stress_with_monitoring(
        self,
        duration: int,
        tlb_threads: int,
        tlb_pages: int,
        use_numa: bool = True,
        use_hugepages: bool = True,
    ) -> PerformanceMetrics:
        """
        Run TLB stress test with continuous performance monitoring.

        Args:
            duration: Test duration in seconds
            tlb_threads: Number of TLB threads
            tlb_pages: Pages per thread
            log: Logger instance
            use_numa: Use NUMA interleaving (reduces false regressions)
            use_hugepages: Use hugepages (explores worst-case TLB shootdowns)

        Returns:
            PerformanceMetrics during stress testing
        """
        stress_metrics = PerformanceMetrics(measurement_duration=duration)

        # Start background performance monitoring
        perf_monitor_process = None

        try:
            # Deploy TLB program
            self._deploy_tlb_program()

            # Probe supported events for stress monitoring
            event_support = self._probe_perf_events()
            supported_events = self._get_fallback_events(event_support)

            # Start background perf monitoring with supported events
            perf_cmd = (
                f"perf stat -a -e {supported_events} " f"--timeout {duration * 1000}"
            )
            perf_monitor_process = self.node.execute_async(perf_cmd, sudo=True)

            # Capture interrupts before stress
            interrupts_before = self._get_proc_interrupts()

            # Run the actual TLB stress test
            self._run_tlb_stress_program(
                duration, tlb_threads, tlb_pages, use_numa, use_hugepages
            )

            # Capture interrupts after stress
            interrupts_after = self._get_proc_interrupts()

            # Wait for perf monitoring to complete with extended timeout
            if perf_monitor_process:
                perf_result = perf_monitor_process.wait_result(timeout=300)

                # Parse supported events with fallback
                if event_support.get("dTLB-load-misses", False):
                    stress_metrics.dtlb_load_misses_per_sec = (
                        self._parse_perf_stat_rate(
                            perf_result.stderr, "dTLB-load-misses", duration
                        )
                    )
                if event_support.get("iTLB-load-misses", False):
                    stress_metrics.itlb_load_misses_per_sec = (
                        self._parse_perf_stat_rate(
                            perf_result.stderr, "iTLB-load-misses", duration
                        )
                    )
                if event_support.get("context-switches", False):
                    stress_metrics.context_switches_per_sec = (
                        self._parse_perf_stat_rate(
                            perf_result.stderr, "context-switches", duration
                        )
                    )

            # Calculate IPI deltas
            stress_metrics.resched_ipis_delta = self._calculate_interrupt_delta(
                interrupts_before, interrupts_after, "resched"
            )
            stress_metrics.call_function_ipis_delta = self._calculate_interrupt_delta(
                interrupts_before, interrupts_after, "call_function"
            )

            # Get final steal time
            is_guest = self.detect_environment_type()
            stress_metrics.steal_time_percent = self._get_steal_time_percent(is_guest)

            return stress_metrics

        except Exception:
            if perf_monitor_process:
                try:
                    perf_monitor_process.terminate()  # type: ignore
                except Exception:
                    pass
            raise

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
        analysis: Dict[str, Any] = {
            "pass": True,
            "warnings": [],
            "failures": [],
            "metrics": {},
        }

        # Get environment-specific thresholds
        is_guest = self.detect_environment_type()
        thresholds = self.get_environment_specific_thresholds(is_guest)

        # Calculate degradation percentages
        if baseline.dtlb_load_misses_per_sec > 0:
            dtlb_increase_pct = (
                (stress.dtlb_load_misses_per_sec - baseline.dtlb_load_misses_per_sec)
                / baseline.dtlb_load_misses_per_sec
            ) * 100
            analysis["metrics"]["dtlb_increase_percent"] = dtlb_increase_pct

            if dtlb_increase_pct > thresholds.host_dtlb_misses_increase_percent:
                analysis["warnings"].append(
                    f"Host dTLB misses increased by {dtlb_increase_pct:.1f}% "
                    f"(threshold: {thresholds.host_dtlb_misses_increase_percent}%)"
                )

        # IPI increase analysis
        ipi_total_before = (
            baseline.resched_ipis_delta + baseline.call_function_ipis_delta
        )
        ipi_total_stress = stress.resched_ipis_delta + stress.call_function_ipis_delta

        if ipi_total_before > 0:
            ipi_increase_pct = (
                (ipi_total_stress - ipi_total_before) / ipi_total_before
            ) * 100
            analysis["metrics"]["ipi_increase_percent"] = ipi_increase_pct

            if ipi_increase_pct > thresholds.host_ipis_increase_percent:
                analysis["warnings"].append(
                    f"Host IPIs increased by {ipi_increase_pct:.1f}% "
                    f"(threshold: {thresholds.host_ipis_increase_percent}%)"
                )

        # Guest steal time analysis (only relevant for guest environments)
        if is_guest:
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
        if analysis["failures"]:
            failure_msg = (
                f"Performance test failures: {'; '.join(analysis['failures'])}"
            )
            raise LisaException(failure_msg)

        # Send performance results to notifier for database storage
        if test_result:
            self._send_performance_notification(test_result, analysis)

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
        self.node.execute(f"mkdir -p {self._work}", sudo=True)

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

        # Add NUMA interleaving to reduce false regressions from locality imbalance
        if use_numa:
            # Check if numactl is available before using it
            numactl_check = self.node.execute("command -v numactl", no_error_log=True)
            if numactl_check.exit_code == 0:
                tlb_cmd = f"numactl --interleave=all {tlb_cmd}"
            else:
                self._log.info(
                    "numactl not available - running without NUMA interleaving"
                )

        # Add hugepage flags for worst-case TLB shootdown scenarios
        if use_hugepages:
            # Set transparent hugepages to 'always' for this process
            hugepage_setup = "echo always > /sys/kernel/mm/transparent_hugepage/enabled"
            self.node.execute(hugepage_setup, sudo=True)

        self.node.execute(tlb_cmd, timeout=duration + 300)

    def _parse_perf_stat_rate(
        self, perf_output: str, event_name: str, duration: float
    ) -> float:
        """Parse perf stat output to extract event rate per second."""
        try:
            # Look for lines like "     1,234,567      dTLB-load-misses"
            pattern = rf"([\d,]+)\s+{re.escape(event_name)}"
            match = re.search(pattern, perf_output)
            if match:
                count_str = match.group(1).replace(",", "")
                count = float(count_str)
                return count / duration
        except Exception:
            pass
        return 0.0

    def _get_proc_interrupts(self) -> Dict[str, int]:
        """Get current interrupt counts from /proc/interrupts."""
        try:
            cat = self.node.tools[Cat]
            interrupts_output = cat.read("/proc/interrupts")

            interrupts = {}
            for line in interrupts_output.split("\n"):
                if "resched" in line.lower():
                    # Sum across all CPUs
                    numbers = re.findall(r"\d+", line)
                    interrupts["resched"] = sum(
                        int(n) for n in numbers[1:] if n.isdigit()
                    )
                elif "call_function" in line.lower() or "function_call" in line.lower():
                    numbers = re.findall(r"\d+", line)
                    interrupts["call_function"] = sum(
                        int(n) for n in numbers[1:] if n.isdigit()
                    )

            return interrupts
        except Exception:
            return {}

    def _calculate_interrupt_delta(
        self, before: Dict[str, int], after: Dict[str, int], interrupt_type: str
    ) -> int:
        """Calculate interrupt count delta."""
        before_count = before.get(interrupt_type, 0)
        after_count = after.get(interrupt_type, 0)
        return max(0, after_count - before_count)

    def _get_steal_time_percent(self, is_guest: bool = True) -> float:
        """
        Get current steal time percentage.

        Args:
            is_guest: Whether running in guest environment

        Returns:
            Steal time percentage (0.0 if host environment)
        """
        if not is_guest:
            # Host environments don't have meaningful steal time
            return 0.0

        try:
            cat = self.node.tools[Cat]
            stat_output = cat.read("/proc/stat")

            # Parse first CPU line: cpu user nice system idle iowait irq
            # softirq steal guest
            cpu_line = stat_output.split("\n")[0]
            values = cpu_line.split()[1:]  # Skip 'cpu' label

            if len(values) >= 8:
                steal = int(values[7])
                total = sum(int(v) for v in values)
                return (steal / total) * 100 if total > 0 else 0.0
        except Exception:
            pass
        return 0.0

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

                # Filter and categorize critical issues
                critical_patterns = [
                    "BUG:",
                    "soft lockup",
                    "hard lockup",
                    "rcu_sched",
                    "kernel NULL pointer",
                    "unable to handle",
                    "Call Trace",
                    "Kernel panic",
                    "hung task",
                    "watchdog",
                    "stall",
                ]

                for error_line in error_lines:
                    if error_line.strip():
                        # Check if this is a critical error
                        is_critical = any(
                            pattern.lower() in error_line.lower()
                            for pattern in critical_patterns
                        )

                        if is_critical:
                            issues.append(
                                f"Critical kernel error: {error_line.strip()}"
                            )
            else:
                pass

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
