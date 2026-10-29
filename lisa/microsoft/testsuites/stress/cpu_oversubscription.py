# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
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
from lisa.tools import Dmesg, Lscpu, StressNg


@TestSuiteMetadata(
    area="cpu",
    category="stress",
    description="""
    Validates guest behavior on CPU-oversubscribed VM sizes (e.g. DTv7, DTav7,
    Asv3), where the host reserves only part of the advertised vCPU capacity
    and may throttle the VM under host contention. Also meaningful on regular
    sizes as a baseline for comparison.
    """,
)
class CpuOversubscription(TestSuite):
    # Default sustained load duration. Long enough to likely overlap a host
    # contention window; override with runbook variables for longer runs.
    DEFAULT_DURATION_IN_SECONDS = 1800
    # Length of each throughput/steal sampling window.
    DEFAULT_WINDOW_IN_SECONDS = 60
    # Oversubscribed sizes promise a 50% CPU performance floor. Use a looser
    # bound so jitter between windows does not cause false failures.
    MIN_THROUGHPUT_RATIO = 0.4
    # Leaves room for stress-ng install and window overhead.
    TIMEOUT = DEFAULT_DURATION_IN_SECONDS * 3

    @TestCaseMetadata(
        description="""
        Runs a sustained all-vCPU stress-ng cpu load, then verifies the guest
        kernel logged no new soft lockups, RCU stalls, or call traces. These
        indicate the host is starving the guest badly enough to destabilize
        the kernel.

        Runbook variable "cpu_oversub_duration" overrides the load duration
        in seconds.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(unsupported_os=[BSD, Windows]),
    )
    def verify_no_soft_lockup_under_cpu_pressure(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        duration = int(
            variables.get("cpu_oversub_duration", self.DEFAULT_DURATION_IN_SECONDS)
        )
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

        new_errors = [line for line in errors_after if line not in errors_before]
        assert_that(new_errors).described_as(
            "guest kernel reported soft lockups, RCU stalls, or call traces "
            "under sustained CPU load. On oversubscribed sizes this means host "
            "throttling is starving the guest; compare with the base VM size "
            "on the same image to confirm."
        ).is_empty()

    @TestCaseMetadata(
        description="""
        Runs back-to-back stress-ng cpu windows on all vCPUs, recording per-window
        throughput (bogo ops/s) and steal time from /proc/stat. Reports steal
        percentiles and throughput spread as perf metrics, and fails only if the
        slowest window drops far below the fastest one.

        Runbook variables "cpu_oversub_duration" and "cpu_oversub_window"
        override the total duration and window length in seconds.
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
        duration = int(
            variables.get("cpu_oversub_duration", self.DEFAULT_DURATION_IN_SECONDS)
        )
        window = int(
            variables.get("cpu_oversub_window", self.DEFAULT_WINDOW_IN_SECONDS)
        )
        window_count = max(1, duration // window)
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
        min_ratio = min(throughputs) / max_throughput if max_throughput else 0.0
        metrics = {
            "steal_percent_p50": (self._percentile(steal_percents, 50), "%"),
            "steal_percent_p90": (self._percentile(steal_percents, 90), "%"),
            "steal_percent_p99": (self._percentile(steal_percents, 99), "%"),
            "steal_percent_max": (max(steal_percents), "%"),
            "cpu_bogo_ops_per_sec_p50": (self._percentile(throughputs, 50), "ops/s"),
            "cpu_bogo_ops_per_sec_min": (min(throughputs), "ops/s"),
            "cpu_throughput_min_to_max_ratio": (min_ratio, ""),
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
            f"min/max throughput ratio = {min_ratio:.2f}"
        )

        assert_that(min_ratio).described_as(
            "slowest CPU window fell below the oversubscription performance "
            "floor relative to the fastest window. Check steal_percent metrics "
            "and host contention for this VM."
        ).is_greater_than_or_equal_to(self.MIN_THROUGHPUT_RATIO)

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
