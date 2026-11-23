# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from collections import Counter
from functools import partial
from typing import Dict, List, Optional, Tuple

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.base_tools import Cat
from lisa.messages import MetricRelativity, send_unified_perf_message
from lisa.operating_system import BSD, Windows
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import AzureNodeSchema
from lisa.testsuite import TestResult
from lisa.tools import Chrony, Dmesg, Lscpu, StressNg
from lisa.util import LisaException, SkippedException, check_till_timeout
from lisa.util.parallel import run_in_parallel
from lisa.util.perf_timer import create_timer


@TestSuiteMetadata(
    area="cpu",
    category="stress",
    description="""
    Validates guest stability and CPU performance characteristics on VM sizes
    that use CPU oversubscription, including DTv7, DTav7, and Asv3.
    Oversubscription policy and expected performance behavior may vary by
    family. Also meaningful on regular sizes as a baseline for comparison.
    """,
)
class CpuOversubscription(TestSuite):
    # Sustained load duration. Long enough to likely overlap a host contention
    # window while keeping each test case around half an hour.
    DURATION_IN_SECONDS = 1800
    # Length of each throughput/steal/timesync sampling window. Must divide
    # DURATION_IN_SECONDS so all samples have equal length.
    WINDOW_IN_SECONDS = 60
    WINDOW_COUNT = DURATION_IN_SECONDS // WINDOW_IN_SECONDS
    # Experimental variability guardrails, NOT the contractual performance
    # floors. Below these, a warning is logged; they do not fail the test until
    # a baseline methodology against the base D-series size is agreed. Each is
    # set below its family's floor to allow for window-to-window jitter:
    # DTv7/DTav7 floor is 50%, Asv3/Adsv3 floor is 75%.
    DT_MIN_TO_PEAK_GUARDRAIL = 0.4
    A_SERIES_MIN_TO_PEAK_GUARDRAIL = 0.65
    # Used for sizes outside these families, e.g. base D-series baseline runs.
    DEFAULT_MIN_TO_PEAK_GUARDRAIL = DT_MIN_TO_PEAK_GUARDRAIL
    # Contractual floors from the OK2GoLive doc, as a fraction of baseline
    # throughput. Enforced only for sizes listed in BASELINE_OPS_PER_SEC.
    DT_PERFORMANCE_FLOOR = 0.5
    A_SERIES_PERFORMANCE_FLOOR = 0.75
    # Standard sizes should see no degradation; this provisional tolerance
    # allows for normal run-to-run variation between baseline and test runs.
    STANDARD_PERFORMANCE_FLOOR = 0.9
    # Normal throughput (p50 bogo ops/s, 60s windows) measured on an unpacked
    # AMD Gen 10 TIP node, Ubuntu 24.04, pipeline run 164823640. Keys are
    # lowercase sizes without the "Standard_" prefix. Sizes not listed only
    # collect data. Re-measure if the image, stress-ng version or window changes.
    BASELINE_OPS_PER_SEC: Dict[str, float] = {
        "dt2as_v7": 3288.0,
        "dt32ads_v7": 51853.0,
    }
    # e.g. Standard_DT4s_v7, DT8ads_v7
    _dt_size_pattern = re.compile(r"^(Standard_)?DT\d+[a-z]*_v7$", re.IGNORECASE)
    # e.g. Standard_A4s_v3, A8ds_v3 (not legacy Av2 sizes)
    _a_series_size_pattern = re.compile(r"^(Standard_)?A\d+[a-z]*_v3$", re.IGNORECASE)
    # DURATION plus room for stress-ng install, the per-window stress-ng
    # startup/teardown overhead, and multi-VM setup.
    TIMEOUT = 7200
    # Extra load time after the last timesync sample, so every sample is taken
    # while stress-ng is still running.
    TIMESYNC_LOAD_MARGIN_IN_SECONDS = 30
    # VMs loaded at once in the multi-VM test. Enough for several VMs to
    # plausibly share a host, while keeping the cost of one run bounded.
    MULTI_VM_COUNT = 4
    # Provisional bound on chrony's system clock offset under load. Azure's
    # PTP-based sync normally keeps the offset well under 1 ms, so 100 ms
    # indicates a real clock disruption rather than normal jitter.
    PROVISIONAL_MAX_CLOCK_OFFSET_IN_SECONDS = 0.1
    # Kernel messages indicating the guest clocksource was disrupted.
    _clocksource_error_pattern = re.compile(
        r"clocksource.*unstable|Marking clocksource .* as unstable|"
        r"TSC.*(unstable|halts)|timekeeping watchdog",
        re.IGNORECASE,
    )

    @TestCaseMetadata(
        description="""
        Runs a 30-minute all-vCPU stress-ng cpu load, then verifies the guest
        kernel logged no new soft lockups, RCU stalls, or call traces. This
        confirms guest stability while all guest vCPUs are busy; it does not
        itself create or prove host-level contention.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(unsupported_os=[BSD, Windows]),
    )
    def verify_no_soft_lockup_under_cpu_pressure(self, node: Node, log: Logger) -> None:
        duration = self.DURATION_IN_SECONDS
        thread_count = node.tools[Lscpu].get_thread_count()
        dmesg = node.tools[Dmesg]
        stress_ng = node.tools[StressNg]

        errors_before = self._get_kernel_error_lines(dmesg)
        log.info(
            f"starting {duration}s cpu oversubscription stress on "
            f"{thread_count} vCPUs of node '{node.name}'"
        )
        stress_ng.launch_cpu(num_cores=thread_count, timeout_in_seconds=duration)
        errors_after = self._get_kernel_error_lines(dmesg)

        # Multiset difference, so a repeat of an error line already present
        # before the load is still counted as new.
        new_errors = list((Counter(errors_after) - Counter(errors_before)).elements())
        assert_that(new_errors).described_as(
            "the guest reported kernel stability errors during sustained CPU "
            "pressure. Review host contention and reproduce on the "
            "corresponding base VM size."
        ).is_empty()

    @TestCaseMetadata(
        description="""
        Runs 30 back-to-back 60-second stress-ng cpu windows on all vCPUs,
        recording per-window throughput (bogo ops/s) and steal time from
        /proc/stat, and publishes them as perf metrics. Steal time is telemetry
        only; Hyper-V may not expose host throttling as guest steal time, so
        zero steal does not prove there was no contention.

        For sizes with a measured baseline (BASELINE_OPS_PER_SEC), the test
        also reports throughput as a percentage of it, and fails if the slowest
        window is below the size family's floor: 50% for DTv7/DTav7, 75% for
        Asv3, and a provisional 90% for standard sizes. Other sizes only
        collect data.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(unsupported_os=[BSD, Windows]),
    )
    def perf_cpu_steal_time(
        self,
        node: Node,
        log: Logger,
        result: TestResult,
    ) -> None:
        _, baseline_ratio = self._run_cpu_windows_and_report(
            node=node,
            log=log,
            result=result,
            test_case_name="perf_cpu_steal_time",
            baseline_ops_per_sec=self._get_baseline_ops_per_sec(node),
        )
        if baseline_ratio is not None:
            floor = self._get_performance_floor(node)
            assert_that(baseline_ratio).described_as(
                f"slowest window on '{node.name}' ({self._get_vm_size(node)}) "
                f"reached {baseline_ratio:.0%} of the baseline, below the "
                f"{floor:.0%} floor for this size family. Confirm the baseline "
                f"came from an unpacked run of the same size, then review host "
                f"contention."
            ).is_greater_than_or_equal_to(floor)

    @TestCaseMetadata(
        description="""
        Approximates a densely packed host by running the same back-to-back
        60-second stress-ng cpu windows for 30 minutes concurrently on several
        VMs of the requested size,
        so they compete for host CPU if Azure places them on the same node.
        Publishes per-VM throughput and steal metrics plus the lowest
        min-to-peak ratio across all VMs, and fails if any VM logs new soft
        lockups, RCU stalls, or call traces.

        Limitations: LISA cannot choose the host, so the VMs may land on
        different nodes and see no contention. It cannot set the node overcommit
        level or mix DT and standard D sizes, because the pipeline deploys one
        size per run. It therefore does NOT validate the OK2GoLive packing
        scenarios or the standard-VM no-degradation requirement; those need a
        platform-packed node. Use it as supporting evidence alongside a run on
        the corresponding base D-series size.

        For sizes with a measured baseline (BASELINE_OPS_PER_SEC), the test
        also fails if any VM's slowest window is below its size family's floor,
        as in perf_cpu_steal_time.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=MULTI_VM_COUNT,
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_cpu_concurrent_load_multi_vm(
        self,
        environment: Environment,
        log: Logger,
        result: TestResult,
    ) -> None:
        # Nodes.list() returns a generator; materialize it for len() and reuse.
        nodes = list(environment.nodes.list())
        errors_before = {
            node.name: self._get_kernel_error_lines(node.tools[Dmesg]) for node in nodes
        }
        log.info(
            f"starting {self.DURATION_IN_SECONDS}s concurrent cpu load on "
            f"{len(nodes)} VMs ({self.WINDOW_COUNT} x {self.WINDOW_IN_SECONDS}s "
            f"windows each)"
        )
        node_results = run_in_parallel(
            [
                partial(
                    self._run_cpu_windows_and_report,
                    node=node,
                    log=log,
                    result=result,
                    test_case_name="perf_cpu_concurrent_load_multi_vm",
                    baseline_ops_per_sec=self._get_baseline_ops_per_sec(node),
                )
                for node in nodes
            ],
            log,
        )
        ratios = [min_to_peak for min_to_peak, _ in node_results]

        lowest_ratio = min(ratios)
        send_unified_perf_message(
            node=nodes[0],
            test_result=result,
            test_case_name="perf_cpu_concurrent_load_multi_vm",
            metric_name="cpu_throughput_min_to_peak_ratio_lowest_vm",
            metric_value=lowest_ratio,
            metric_relativity=MetricRelativity.HigherIsBetter,
            tool="stress-ng",
        )
        log.info(
            f"concurrent cpu load summary across {len(nodes)} VMs: per-VM "
            f"min-to-peak ratios "
            f"{[round(ratio, 3) for ratio in ratios]}, lowest {lowest_ratio:.3f}"
        )

        new_errors: Dict[str, List[str]] = {}
        for node in nodes:
            errors_after = self._get_kernel_error_lines(node.tools[Dmesg])
            node_new_errors = list(
                (Counter(errors_after) - Counter(errors_before[node.name])).elements()
            )
            if node_new_errors:
                new_errors[node.name] = node_new_errors
        assert_that(new_errors).described_as(
            "one or more VMs reported kernel stability errors during concurrent "
            "CPU load. Review host contention for those VMs and reproduce on "
            "the corresponding base VM size."
        ).is_empty()

        below_floor: Dict[str, str] = {}
        for node, (_, baseline_ratio) in zip(nodes, node_results):
            floor = self._get_performance_floor(node)
            if baseline_ratio is not None and baseline_ratio < floor:
                below_floor[node.name] = (
                    f"{self._get_vm_size(node)}: {baseline_ratio:.0%} of "
                    f"baseline, floor {floor:.0%}"
                )
        assert_that(below_floor).described_as(
            "one or more VMs' slowest window fell below the floor for their "
            "size family. Confirm each baseline came from an unpacked run of "
            "the same size, then review host contention."
        ).is_empty()

    def _run_cpu_windows_and_report(
        self,
        node: Node,
        log: Logger,
        result: TestResult,
        test_case_name: str,
        baseline_ops_per_sec: Optional[float],
    ) -> Tuple[float, Optional[float]]:
        """
        Runs back-to-back cpu windows on all vCPUs of the node and publishes the
        metrics. Returns the min-to-peak throughput ratio, and the slowest
        window as a fraction of the baseline (None if no baseline is given).
        """
        window_count = self.WINDOW_COUNT
        window = self.WINDOW_IN_SECONDS
        thread_count = node.tools[Lscpu].get_thread_count()
        stress_ng = node.tools[StressNg]

        throughputs: List[float] = []
        steal_percents: List[float] = []
        for index in range(window_count):
            steal_before, total_before = self._read_cpu_stat(node)
            throughput = stress_ng.launch_cpu_with_metrics(
                num_workers=thread_count, timeout_in_seconds=window
            )
            steal_after, total_after = self._read_cpu_stat(node)
            total_delta = total_after - total_before
            steal_percent = (
                100.0 * (steal_after - steal_before) / total_delta
                if total_delta
                else 0.0
            )
            throughputs.append(throughput)
            steal_percents.append(steal_percent)
            log.info(
                f"cpu oversubscription window {index + 1}/{window_count} on "
                f"'{node.name}': {throughput:.2f} bogo ops/s, "
                f"steal {steal_percent:.2f}%"
            )

        max_throughput = max(throughputs)
        min_to_peak_ratio = min(throughputs) / max_throughput if max_throughput else 0.0
        metrics = {
            "steal_percent_p50": (self._percentile(steal_percents, 50), "%"),
            "steal_percent_p90": (self._percentile(steal_percents, 90), "%"),
            "steal_percent_p99": (self._percentile(steal_percents, 99), "%"),
            "steal_percent_max": (max(steal_percents), "%"),
            "cpu_bogo_ops_per_sec_p50": (self._percentile(throughputs, 50), "ops/s"),
            "cpu_bogo_ops_per_sec_min": (min(throughputs), "ops/s"),
            "cpu_throughput_min_to_peak_ratio": (min_to_peak_ratio, ""),
        }
        baseline_ratio: Optional[float] = None
        if baseline_ops_per_sec is not None:
            baseline_ratio = min(throughputs) / baseline_ops_per_sec
            metrics["cpu_throughput_min_percent_of_baseline"] = (
                baseline_ratio * 100,
                "%",
            )
            metrics["cpu_throughput_p50_percent_of_baseline"] = (
                self._percentile(throughputs, 50) / baseline_ops_per_sec * 100,
                "%",
            )
        for name, (value, unit) in metrics.items():
            relativity = (
                MetricRelativity.LowerIsBetter
                if name.startswith("steal")
                else MetricRelativity.HigherIsBetter
            )
            send_unified_perf_message(
                node=node,
                test_result=result,
                test_case_name=test_case_name,
                metric_name=name,
                metric_value=value,
                metric_unit=unit,
                metric_relativity=relativity,
                tool="stress-ng",
            )
        metric_summary = ", ".join(
            f"{name}={value:.3f}{unit}" for name, (value, unit) in metrics.items()
        )
        log.info(
            f"cpu oversubscription summary on '{node.name}' ({thread_count} vCPUs, "
            f"{window_count} x {window}s windows): {metric_summary}"
        )
        guardrail = self._get_min_to_peak_guardrail(node)
        if min_to_peak_ratio < guardrail:
            log.warning(
                f"cpu oversubscription min-to-peak throughput ratio "
                f"{min_to_peak_ratio:.2f} "
                f"on '{node.name}' is below provisional guardrail "
                f"{guardrail}. Compare with a run on the "
                f"corresponding base D-series size."
            )
        return min_to_peak_ratio, baseline_ratio

    @TestCaseMetadata(
        description="""
        Verifies guest time sync stays accurate while all vCPUs are busy.
        Existing timesync tests run on an idle VM; CPU throttling or live
        migration on oversubscribed hosts can cause clock drift or jumps that
        only show under load.

        Runs one 30-minute stress-ng cpu load on all vCPUs and, while it runs,
        reads chrony's system clock offset and leap status every 60 seconds.
        Fails if the offset exceeds a provisional 100 ms bound, chrony loses
        sync, or the kernel logs new clocksource instability messages.
        Publishes max and p99 offset as perf metrics.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(unsupported_os=[BSD, Windows]),
    )
    def verify_timesync_under_cpu_pressure(
        self,
        node: Node,
        log: Logger,
        result: TestResult,
    ) -> None:
        duration = self.DURATION_IN_SECONDS
        window = self.WINDOW_IN_SECONDS
        window_count = self.WINDOW_COUNT
        thread_count = node.tools[Lscpu].get_thread_count()
        stress_ng = node.tools[StressNg]
        dmesg = node.tools[Dmesg]
        # Installing chrony changes the image, so later cases need a clean VM.
        if node.execute("command -v chronyc", shell=True).exit_code != 0:
            node.mark_dirty()
        chrony = node.tools[Chrony]

        try:
            chrony.check_tracking()
        except LisaException as error:
            raise SkippedException(
                f"chrony is not synchronized on '{node.name}' before the load, "
                f"so offsets under load cannot be judged. Run "
                f"verify_timesync_chrony to diagnose: {error}"
            ) from error

        clock_errors_before = self._get_clocksource_error_lines(dmesg)
        offsets: List[float] = []
        unsynchronized_samples: List[int] = []
        log.info(
            f"starting {duration}s timesync-under-load check on {thread_count} "
            f"vCPUs of node '{node.name}', sampling every {window}s"
        )
        stress_process = stress_ng.launch_cpu_async(
            num_cores=thread_count,
            timeout_in_seconds=duration + self.TIMESYNC_LOAD_MARGIN_IN_SECONDS,
        )
        timer = create_timer()
        try:
            for index in range(window_count):
                next_sample_at = (index + 1) * window
                check_till_timeout(
                    lambda target=next_sample_at: timer.elapsed(False) >= target,
                    timeout_message=(
                        f"waiting for timesync sample {index + 1}/{window_count}"
                    ),
                    # bounded by the sample time plus a small scheduling margin
                    timeout=next_sample_at + 30,
                )
                assert_that(stress_process.is_running()).described_as(
                    "stress-ng exited before the load duration ended, so later "
                    "samples would not be under load. Check stress-ng output."
                ).is_true()
                offset, is_synchronized = chrony.get_tracking_status()
                offsets.append(offset)
                if not is_synchronized:
                    unsynchronized_samples.append(index + 1)
                log.info(
                    f"timesync under load sample {index + 1}/{window_count}: "
                    f"offset {offset * 1000:.3f} ms, "
                    f"synchronized {is_synchronized}"
                )
            stress_process.wait_result(
                # remaining load margin plus time for stress-ng teardown
                timeout=self.TIMESYNC_LOAD_MARGIN_IN_SECONDS + 120,
                expected_exit_code=0,
                expected_exit_code_failure_message="stress-ng cpu stressor failed",
            )
        finally:
            if stress_process.is_running():
                stress_process.kill()
        clock_errors_after = self._get_clocksource_error_lines(dmesg)

        max_offset = max(offsets)
        for name, value in {
            "clock_offset_ms_p99": self._percentile(offsets, 99) * 1000,
            "clock_offset_ms_max": max_offset * 1000,
        }.items():
            send_unified_perf_message(
                node=node,
                test_result=result,
                test_case_name="verify_timesync_under_cpu_pressure",
                metric_name=name,
                metric_value=value,
                metric_unit="ms",
                metric_relativity=MetricRelativity.LowerIsBetter,
                tool="chrony",
            )
        log.info(
            f"timesync under load summary on '{node.name}' ({thread_count} vCPUs, "
            f"{window_count} x {window}s samples): clock_offset_ms_p99="
            f"{self._percentile(offsets, 99) * 1000:.3f}, clock_offset_ms_max="
            f"{max_offset * 1000:.3f}, unsynchronized_samples="
            f"{len(unsynchronized_samples)}"
        )

        new_clock_errors = list(
            (Counter(clock_errors_after) - Counter(clock_errors_before)).elements()
        )
        assert_that(new_clock_errors).described_as(
            "the guest kernel reported clocksource instability during sustained "
            "CPU pressure. Review host contention and reproduce on the "
            "corresponding base VM size."
        ).is_empty()
        assert_that(unsynchronized_samples).described_as(
            "chrony lost synchronization (leap status not Normal) at these "
            "sample numbers during CPU pressure. Check 'chronyc tracking' and "
            "the PTP clock source on this VM."
        ).is_empty()
        assert_that(max_offset).described_as(
            "guest clock offset from NTP time exceeded the provisional bound "
            "during CPU pressure. Compare with the corresponding base VM size "
            "to tell oversubscription effects from image issues."
        ).is_less_than_or_equal_to(self.PROVISIONAL_MAX_CLOCK_OFFSET_IN_SECONDS)

    def _get_vm_size(self, node: Node) -> str:
        try:
            return str(
                node.capability.get_extended_runbook(AzureNodeSchema, AZURE).vm_size
            )
        except LisaException:
            # Non-Azure node with another platform's schema; no size family.
            return ""

    def _get_min_to_peak_guardrail(self, node: Node) -> float:
        vm_size = self._get_vm_size(node)
        if self._a_series_size_pattern.match(vm_size):
            return self.A_SERIES_MIN_TO_PEAK_GUARDRAIL
        if self._dt_size_pattern.match(vm_size):
            return self.DT_MIN_TO_PEAK_GUARDRAIL
        return self.DEFAULT_MIN_TO_PEAK_GUARDRAIL

    def _get_performance_floor(self, node: Node) -> float:
        vm_size = self._get_vm_size(node)
        if self._a_series_size_pattern.match(vm_size):
            return self.A_SERIES_PERFORMANCE_FLOOR
        if self._dt_size_pattern.match(vm_size):
            return self.DT_PERFORMANCE_FLOOR
        return self.STANDARD_PERFORMANCE_FLOOR

    def _get_baseline_ops_per_sec(self, node: Node) -> Optional[float]:
        vm_size = self._get_vm_size(node).strip().lower()
        return self.BASELINE_OPS_PER_SEC.get(re.sub(r"^standard_", "", vm_size))

    def _get_clocksource_error_lines(self, dmesg: Dmesg) -> List[str]:
        output = dmesg.get_output(force_run=True)
        return [
            line
            for line in output.splitlines()
            if self._clocksource_error_pattern.search(line)
        ]

    def _get_kernel_error_lines(self, dmesg: Dmesg) -> List[str]:
        output = dmesg.check_kernel_errors(force_run=True, throw_error=False)
        return [line for line in output.splitlines() if line.strip()]

    def _read_cpu_stat(self, node: Node) -> Tuple[int, int]:
        # Aggregate line: "cpu user nice system idle iowait irq softirq steal ..."
        first_line = node.tools[Cat].read("/proc/stat", force_run=True).splitlines()[0]
        fields = [int(value) for value in first_line.split()[1:9]]
        # guest/guest_nice are already included in user/nice, so only the first
        # 8 fields make up total time; steal is the 8th.
        return fields[7], sum(fields)

    def _percentile(self, values: List[float], percent: int) -> float:
        ordered = sorted(values)
        index = min(len(ordered) - 1, int(round(percent / 100 * (len(ordered) - 1))))
        return ordered[index]
