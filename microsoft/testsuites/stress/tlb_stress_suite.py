# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict, List, cast

from lisa import (
    Environment,
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestResult,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.features import SerialConsole
from lisa.tools import Lscpu, StressNg, TlbStress


@TestSuiteMetadata(
    area="mshv",
    category="stress",
    description="""
    TLB (Translation Lookaside Buffer) stress testing suite.

    This test suite focuses on creating intensive TLB pressure to reveal
    performance degradation under heavy virtual memory operations.
    TLB stress testing is crucial for:

    - Validating TLB performance under memory pressure scenarios
    - Detecting performance regressions in virtual memory subsystems
    - Stress testing VM environments with intensive memory operations
    - Benchmarking TLB efficiency across different CPU architectures

    The suite combines custom TLB flush programs with stress-ng stressors
    to create comprehensive TLB pressure through frequent memory
    unmapping/remapping operations.
    """,
)
class TlbStressTestSuite(TestSuite):
    # Test timeout: Expected ~9 minutes, allowing 3x buffer for CI variability
    TIME_OUT = 3600

    def _calculate_optimal_thread_count(self, node: RemoteNode) -> int:
        """Calculate optimal TLB stress thread count: min(2×vCPUs, 64) for Azure VMs"""
        cpu_count = node.tools[Lscpu].get_core_count()
        optimal_threads = min(cpu_count * 2, 64)
        return optimal_threads

    def _calculate_stress_workers(self, node: RemoteNode, base_workers: int = 2) -> int:
        """Scale stress-ng workers based on CPU count for different SKU sizes"""
        cpu_count = node.tools[Lscpu].get_core_count()
        # Scale workers: base + (cpus/4), capped at reasonable maximum
        scaled_workers = min(base_workers + max(1, cpu_count // 4), 16)
        return scaled_workers

    @TestCaseMetadata(
        description="""
        Execute basic TLB stress test with custom memory pressure.

        This test creates intensive TLB pressure through rapid memory
        mapping/unmapping operations combined with stress-ng VM stressors.
        Validates system stability under heavy TLB activity.
        """,
        priority=2,
        requirement=simple_requirement(min_core_count=2, min_memory_mb=1024),
        timeout=TIME_OUT,
    )
    def tlb_stress_basic(
        self,
        log: Logger,
        environment: Environment,
        result: TestResult,
    ) -> None:
        """Execute basic TLB stress test."""
        nodes = [cast(RemoteNode, node) for node in environment.nodes.list()]

        log.debug("Starting basic TLB stress test...")

        # Test configuration - scale for Azure VMs
        test_duration = 300
        tlb_threads = self._calculate_optimal_thread_count(nodes[0])
        tlb_pages = 1000

        log.debug(
            f"Using {tlb_threads} TLB stress threads based on "
            f"{nodes[0].tools[Lscpu].get_core_count()} vCPUs"
        )

        try:
            # Deploy and run TLB stress
            tlb_tool = nodes[0].tools[TlbStress]
            stress_ng = nodes[0].tools[StressNg]
            tlb_tool.install()

            # Guest workload probe to exercise throughput/latency gate
            log.debug("Running guest workload probe to establish baseline...")
            stress_ng.run(
                "--matrix 1 --matrix-size 128 --timeout 30 --metrics-brief",
                force_run=True,
                timeout=40,
            )

            # Run stress test
            tlb_tool.run_stress_with_monitoring(
                duration=test_duration,
                tlb_threads=tlb_threads,
                tlb_pages=tlb_pages,
            )

            log.debug("Basic TLB stress test completed successfully")

        except Exception as e:
            self._check_panic(nodes)
            log.error(f"TLB stress test failed: {e}")
            raise e

    @TestCaseMetadata(
        description="""
        Comprehensive TLB stress test with performance monitoring.

        This test combines custom TLB flush operations with stress-ng stressors
        to create maximum TLB pressure while monitoring performance degradation.
        Features baseline/stress comparison with configurable thresholds to detect
        performance regressions in virtual memory subsystems.
        """,
        priority=1,
        requirement=simple_requirement(min_core_count=4, min_memory_mb=2048),
        timeout=TIME_OUT,
    )
    def tlb_stress_stressng(
        self,
        log: Logger,
        environment: Environment,
        result: TestResult,
    ) -> None:
        """Execute comprehensive TLB stress test with performance monitoring."""
        nodes = [cast(RemoteNode, node) for node in environment.nodes.list()]

        log.debug("Starting comprehensive TLB stress test with performance monitoring")

        try:
            stress_ng = nodes[0].tools[StressNg]
            tlb_tool = nodes[0].tools[TlbStress]
            tlb_tool.install()

            # Guest workload probe to exercise throughput/latency gate
            log.debug("Running guest workload probe to establish baseline...")
            stress_ng.run(
                "--matrix 1 --matrix-size 128 --timeout 30 --metrics-brief",
                force_run=True,
                timeout=40,
            )

            # Detect environment type and get appropriate thresholds
            is_guest = tlb_tool.detect_environment_type()
            thresholds = tlb_tool.get_environment_specific_thresholds(is_guest)

            log.debug(
                f"Environment detected: "
                f"{'Guest (VM)' if is_guest else 'Host (Bare Metal)'}"
            )
            log.debug(
                f"Performance thresholds: "
                f"throughput <{thresholds.guest_throughput_degradation_percent}%, "
                f"latency <{thresholds.guest_p95_latency_increase_percent}%, "
                f"steal <{thresholds.guest_steal_time_increase_points}%"
            )

            # Phase 1: Capture baseline performance metrics
            log.debug("Phase 1: Capturing baseline performance metrics...")
            baseline_metrics = tlb_tool.capture_performance_baseline()

            # Phase 2: Run combined TLB + stress-ng test with monitoring
            log.debug(
                "Phase 2: Running combined TLB + stress-ng stressors with monitoring..."
            )

            # Sequential VM memory stressors first (warm-up phase)
            log.debug("Running warm-up stressors sequentially...")

            # Scale worker counts based on CPU count
            vm_workers = self._calculate_stress_workers(nodes[0], base_workers=4)
            mmap_workers = self._calculate_stress_workers(nodes[0], base_workers=2)

            # Basic VM stressor (scaled workers, 128MB each, 60s)
            log.debug(f"Running vm stressor: {vm_workers} workers, 128MB, 60s")
            stress_ng.run(
                f"--vm {vm_workers} --vm-bytes 128M --timeout 60 --metrics-brief",
                force_run=True,
                timeout=70,
            )

            # Memory mapping stressor (scaled workers, 256MB, 60s)
            log.debug(f"Running mmap stressor: {mmap_workers} workers, 256MB, 60s")
            stress_ng.run(
                f"--mmap {mmap_workers} --mmap-bytes 256M --mmap-file "
                f"--timeout 60 --metrics-brief",
                force_run=True,
                timeout=70,
            )

            # Parallel TLB-intensive stressors with performance monitoring
            log.debug(
                "Running maximum TLB pressure phase with performance monitoring..."
            )

            # Start performance monitoring with portable events
            perf_monitor_process = tlb_tool.node.execute_async(
                "perf stat -e cycles,instructions,cache-misses,page-faults,"
                "context-switches "
                "-I 1000 --append -o perf_stress_output.txt sleep 300",
                cwd=tlb_tool.node.get_working_path(),
                sudo=True,
            )

            # Launch parallel stressors for maximum TLB pressure
            processes = []

            # Custom TLB flush stressor with optimal thread count and 300s duration
            optimal_threads = self._calculate_optimal_thread_count(nodes[0])
            log.debug(
                f"Launching custom TLB stressor: {optimal_threads} threads, "
                f"1000 pages, 300s"
            )
            tlb_cmd = f"{tlb_tool.command} -t {optimal_threads} -p 1000 -d 300"
            tlb_proc = nodes[0].execute_async(tlb_cmd)
            processes.append(tlb_proc)

            # Combined stress-ng stressors running in parallel (300s)
            # Scale workers for larger SKUs
            parallel_vm_workers = self._calculate_stress_workers(
                nodes[0], base_workers=2
            )
            parallel_mmap_workers = self._calculate_stress_workers(
                nodes[0], base_workers=2
            )
            parallel_mremap_workers = self._calculate_stress_workers(
                nodes[0], base_workers=2
            )

            log.debug(
                f"Launching combined stress-ng stressors with scaled workers for 300s: "
                f"vm={parallel_vm_workers}, mmap={parallel_mmap_workers}, "
                f"mremap={parallel_mremap_workers}"
            )
            combined_stress_cmd = (
                f"--vm {parallel_vm_workers} --vm-bytes 64M --vm-populate "
                f"--mmap {parallel_mmap_workers} --mmap-bytes 128M "
                f"--mmap-file --mmap-async "
                f"--mremap {parallel_mremap_workers} --mremap-bytes 128M "
                "--madvise 1 "
                "--timeout 300 --metrics-brief"
            )
            stress_proc = stress_ng.run_async(combined_stress_cmd, force_run=True)
            processes.append(stress_proc)

            # Wait for all parallel processes to complete
            log.debug("Waiting for TLB stressor and combined stress-ng to complete...")
            for i, process in enumerate(processes):
                result_obj = process.wait_result(timeout=330)
                if i == 0:
                    log.debug(
                        f"Custom TLB stressor completed: {result_obj.stdout[:200]}..."
                    )
                else:
                    log.debug(
                        f"Combined stress-ng stressors completed: "
                        f"{result_obj.stdout[:200]}..."
                    )

            # Wait for performance monitoring to complete
            perf_monitor_process.wait_result(timeout=330)

            # Phase 3: Capture stress performance metrics and analyze
            log.debug("Phase 3: Analyzing performance degradation...")
            # Use the same baseline capture method to get consistent metrics
            stress_metrics = tlb_tool.capture_performance_baseline()

            analysis_result = tlb_tool.analyze_performance_degradation(
                baseline_metrics, stress_metrics
            )

            # Report comprehensive results
            self._report_performance_results(analysis_result, result, log)

            log.debug(
                "Comprehensive TLB stress test with performance monitoring "
                "completed successfully"
            )

        except Exception as e:
            self._check_panic(nodes)
            log.error(f"Comprehensive TLB stress test failed: {e}")
            raise e

    # === Private Helper Methods ===

    def _check_panic(self, nodes: List[RemoteNode]) -> None:
        """Check for kernel panic on all nodes"""
        for node in nodes:
            node.features[SerialConsole].check_panic(saved_path=None, force_run=True)

    def _report_performance_results(
        self,
        analysis: Dict[str, Any],
        result: TestResult,
        log: Logger,
    ) -> None:
        """Report performance test results."""
        # Create summary message
        summary_lines = ["=== TLB Stress Performance Analysis ==="]

        # Add metrics
        if "metrics" in analysis:
            summary_lines.append("Performance Metrics:")
            for key, value in analysis["metrics"].items():
                summary_lines.append(f"  {key}: {value:.2f}")

        # Add warnings
        if analysis["warnings"]:
            summary_lines.append("Warnings:")
            for warning in analysis["warnings"]:
                summary_lines.append(f"  ⚠ {warning}")

        # Add failures
        if analysis["failures"]:
            summary_lines.append("Failures:")
            for failure in analysis["failures"]:
                summary_lines.append(f"  ❌ {failure}")

        summary_lines.append(
            f"Overall Result: {'PASS' if analysis['pass'] else 'FAIL'}"
        )

        summary_message = "\n".join(summary_lines)
        log.info(summary_message)

        # Set test result status
        if not analysis["pass"]:
            raise AssertionError(
                f"Performance degradation detected: {'; '.join(analysis['failures'])}"
            )
