# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from collections import Counter
from typing import Any, Dict, List, Tuple

from assertpy import assert_that

from lisa import (
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
from lisa.testsuite import TestResult
from lisa.tools import Chrony, Dmesg, Lscpu, StressNg
from lisa.util import LisaException, SkippedException


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
    # Default sustained load duration. Long enough to likely overlap a host
    # contention window; override with runbook variables for longer runs.
    DEFAULT_DURATION_IN_SECONDS = 1800
    # Upper bound for the runbook-configurable duration, so the load always
    # finishes within the static TIMEOUT below.
    MAX_DURATION_IN_SECONDS = 10800
    # Length of each throughput/steal sampling window.
    DEFAULT_WINDOW_IN_SECONDS = 60
    # Experimental variability guardrail, NOT the contractual 50% performance
    # floor. Below this, a warning is logged; it does not fail the test until a
    # baseline methodology against the base D-series size is agreed.
    PROVISIONAL_MIN_TO_PEAK_RATIO = 0.4
    # MAX_DURATION plus room for stress-ng install and the cumulative startup
    # and teardown overhead of launching one stress-ng process per window.
    TIMEOUT = 14400
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
        Runs a sustained all-vCPU stress-ng cpu load, then verifies the guest
        kernel logged no new soft lockups, RCU stalls, or call traces. This
        confirms guest stability while all guest vCPUs are busy; it does not
        itself create or prove host-level contention.

        Runbook variable "cpu_oversub_duration" overrides the load duration
        in seconds (max 10800).
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(unsupported_os=[BSD, Windows]),
    )
    def verify_no_soft_lockup_under_cpu_pressure(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        duration = self._get_duration(variables)
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
        Runs back-to-back stress-ng cpu windows on all vCPUs, recording per-window
        throughput (bogo ops/s) and steal time from /proc/stat, and publishes
        them as perf metrics. This is a data-collection test: it does not
        validate the 50% performance floor, which needs a baseline from the
        corresponding D-series size. Steal time is telemetry only; Hyper-V may
        not expose host throttling as guest steal time, so zero steal does not
        prove there was no contention.

        Runbook variables "cpu_oversub_duration" (max 10800) and
        "cpu_oversub_window" override the total duration and window length in
        seconds. The duration must be divisible by the window so all samples
        have equal length.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(unsupported_os=[BSD, Windows]),
    )
    def perf_cpu_steal_time(
        self,
        node: Node,
        log: Logger,
        variables: Dict[str, Any],
        result: TestResult,
    ) -> None:
        duration, window = self._get_duration_and_window(variables)
        window_count = duration // window
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
            log.debug(
                f"cpu oversubscription window {index + 1}/{window_count}: "
                f"{throughput:.2f} bogo ops/s, steal {steal_percent:.2f}%"
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
        for name, (value, unit) in metrics.items():
            relativity = (
                MetricRelativity.LowerIsBetter
                if name.startswith("steal")
                else MetricRelativity.HigherIsBetter
            )
            send_unified_perf_message(
                node=node,
                test_result=result,
                test_case_name="perf_cpu_steal_time",
                metric_name=name,
                metric_value=value,
                metric_unit=unit,
                metric_relativity=relativity,
                tool="stress-ng",
            )
        log.info(
            f"cpu oversubscription summary on '{node.name}' over {window_count} "
            f"windows: steal p50/p90/max = "
            f"{metrics['steal_percent_p50'][0]:.2f}/"
            f"{metrics['steal_percent_p90'][0]:.2f}/"
            f"{metrics['steal_percent_max'][0]:.2f}%, "
            f"min-to-peak throughput ratio = {min_to_peak_ratio:.2f}"
        )
        if min_to_peak_ratio < self.PROVISIONAL_MIN_TO_PEAK_RATIO:
            log.warning(
                f"cpu oversubscription min-to-peak throughput ratio "
                f"{min_to_peak_ratio:.2f} "
                f"on '{node.name}' is below provisional guardrail "
                f"{self.PROVISIONAL_MIN_TO_PEAK_RATIO}. Compare with a run on the "
                f"corresponding base D-series size."
            )

    @TestCaseMetadata(
        description="""
        Verifies guest time sync stays accurate while all vCPUs are busy.
        Existing timesync tests run on an idle VM; CPU throttling or live
        migration on oversubscribed hosts can cause clock drift or jumps that
        only show under load.

        Runs back-to-back stress-ng cpu windows on all vCPUs and, between
        windows, reads chrony's system clock offset and leap status. Fails if
        the offset exceeds a provisional 100 ms bound, chrony loses sync, or the
        kernel logs new clocksource instability messages. Publishes max and p99
        offset as perf metrics.

        Runbook variables "cpu_oversub_duration" (max 10800) and
        "cpu_oversub_window" set the total duration and sampling interval in
        seconds; the duration must be divisible by the window.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(unsupported_os=[BSD, Windows]),
    )
    def verify_timesync_under_cpu_pressure(
        self,
        node: Node,
        log: Logger,
        variables: Dict[str, Any],
        result: TestResult,
    ) -> None:
        duration, window = self._get_duration_and_window(variables)
        window_count = duration // window
        thread_count = node.tools[Lscpu].get_thread_count()
        stress_ng = node.tools[StressNg]
        dmesg = node.tools[Dmesg]
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
        for index in range(window_count):
            stress_ng.launch_cpu(num_cores=thread_count, timeout_in_seconds=window)
            offset, is_synchronized = chrony.get_tracking_status()
            offsets.append(offset)
            if not is_synchronized:
                unsynchronized_samples.append(index + 1)
            log.debug(
                f"timesync under load window {index + 1}/{window_count}: "
                f"offset {offset * 1000:.3f} ms, synchronized {is_synchronized}"
            )
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
            f"timesync under load summary on '{node.name}' over {window_count} "
            f"samples: max offset {max_offset * 1000:.3f} ms, "
            f"unsynchronized samples {len(unsynchronized_samples)}"
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

    def _get_duration_and_window(self, variables: Dict[str, Any]) -> Tuple[int, int]:
        duration = self._get_duration(variables)
        window = self._get_int_variable(
            variables, "cpu_oversub_window", self.DEFAULT_WINDOW_IN_SECONDS
        )
        assert_that(window).described_as(
            "cpu_oversub_window must be a positive number of seconds no larger "
            "than cpu_oversub_duration. Fix the runbook variable."
        ).is_greater_than(0).is_less_than_or_equal_to(duration)
        assert_that(duration % window).described_as(
            "cpu_oversub_duration must be divisible by cpu_oversub_window so "
            "all samples use equal durations. Fix the runbook variables."
        ).is_equal_to(0)
        return duration, window

    def _get_clocksource_error_lines(self, dmesg: Dmesg) -> List[str]:
        output = dmesg.get_output(force_run=True)
        return [
            line
            for line in output.splitlines()
            if self._clocksource_error_pattern.search(line)
        ]

    def _get_duration(self, variables: Dict[str, Any]) -> int:
        duration = self._get_int_variable(
            variables, "cpu_oversub_duration", self.DEFAULT_DURATION_IN_SECONDS
        )
        assert_that(duration).described_as(
            f"cpu_oversub_duration must be between 1 and "
            f"{self.MAX_DURATION_IN_SECONDS} seconds to finish within the test "
            f"timeout. Fix the runbook variable."
        ).is_greater_than(0).is_less_than_or_equal_to(self.MAX_DURATION_IN_SECONDS)
        return duration

    def _get_int_variable(
        self, variables: Dict[str, Any], name: str, default: int
    ) -> int:
        value = variables.get(name, default)
        try:
            return int(value)
        except (TypeError, ValueError) as error:
            raise LisaException(
                f"runbook variable '{name}' has invalid value '{value}'. "
                f"Set it to a whole number of seconds, e.g. {default}."
            ) from error

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
