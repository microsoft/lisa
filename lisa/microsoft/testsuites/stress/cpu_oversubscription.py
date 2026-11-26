# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from collections import Counter
from dataclasses import dataclass
from functools import partial
from typing import Dict, List, Optional, Tuple, cast

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    RemoteNode,
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
from lisa.tools import Chrony, Dmesg, Fio, Iperf3, Kill, Lscpu, StressNg
from lisa.util import LisaException, SkippedException, check_till_timeout
from lisa.util.parallel import run_in_parallel
from lisa.util.perf_timer import create_timer


@dataclass
class _CpuWindowResult:
    # slowest window / fastest window on this node
    min_to_peak_ratio: float
    # slowest window / BASELINE_OPS_PER_SEC, None if the size has no baseline
    baseline_ratio: Optional[float]
    p50_ops_per_sec: float
    min_ops_per_sec: float


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
    # Windows per phase in the mixed-size overpacking test. It runs three
    # phases, so 10 x 60s keeps the whole test near 30 minutes of load.
    MIXED_PHASE_WINDOW_COUNT = 10
    # Runtime of each iperf3 and fio measurement on standard VMs. Long enough
    # for a stable average, short enough to repeat with and without DT load.
    IO_MEASURE_SECONDS = 300
    # iperf3 parallel streams, so throughput reaches the VM's network limit.
    IPERF3_PARALLEL_STREAMS = 8
    # fio queue depth for the 4K random-read storage measurement.
    FIO_IODEPTH = 64
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
        baseline_ratio = self._run_cpu_windows_and_report(
            node=node,
            log=log,
            result=result,
            test_case_name="perf_cpu_steal_time",
            baseline_ops_per_sec=self._get_baseline_ops_per_sec(node),
        ).baseline_ratio
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
        ratios = [node_result.min_to_peak_ratio for node_result in node_results]

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
        for node, node_result in zip(nodes, node_results):
            baseline_ratio = node_result.baseline_ratio
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

    @TestCaseMetadata(
        description="""
        Covers the OK2GoLive overpacking scenarios for CPU on a node packed with
        a mix of oversubscribed (DTv7/DTav7/Asv3) and standard VMs. The
        environment must contain both kinds of VM, deployed onto the same
        packed node (for example a single-node TIP session); otherwise the test
        is skipped. LISA does not create the packing or control the overcommit
        level; those come from the deployment.

        Runs three 10-minute phases of 60-second stress-ng cpu windows:
        1. Standard VMs busy, oversubscribed VMs idle: standard-VM reference.
        2. Scenario 2 (packed but quiet): oversubscribed VMs busy, standard VMs
           idle. For sizes with a measured baseline, the slowest window must
           reach at least 90% of it (full speed).
        3. Scenario 1 (everyone busy): all VMs busy. Each standard VM's slowest
           window must reach at least 90% of its phase 1 median (no
           degradation). Each oversubscribed VM's slowest window must reach its
           family's floor (50% for DT, 75% for Asv3) of its baseline, or of its
           phase 2 median for sizes without a baseline.
        Also fails if any VM logs new soft lockups, RCU stalls or call traces.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_cpu_overpacked_node_mixed_sizes(
        self,
        environment: Environment,
        log: Logger,
        result: TestResult,
    ) -> None:
        test_case_name = "perf_cpu_overpacked_node_mixed_sizes"
        nodes = list(environment.nodes.list())
        oversubscribed, standard = self._split_by_oversubscription(nodes)
        errors_before = {
            node.name: self._get_kernel_error_lines(node.tools[Dmesg]) for node in nodes
        }

        log.info(
            f"overpacking phase 1/3 on {len(standard)} standard VMs, "
            f"oversubscribed VMs idle"
        )
        standard_alone = self._run_cpu_phase(
            standard, log, result, test_case_name, "phase1_standard_alone_"
        )
        log.info(
            f"overpacking phase 2/3 (scenario 2) on {len(oversubscribed)} "
            f"oversubscribed VMs, standard VMs idle"
        )
        oversubscribed_quiet = self._run_cpu_phase(
            oversubscribed, log, result, test_case_name, "scenario2_quiet_"
        )
        log.info(f"overpacking phase 3/3 (scenario 1) on all {len(nodes)} VMs")
        all_busy = self._run_cpu_phase(
            nodes, log, result, test_case_name, "scenario1_all_busy_"
        )

        failures: Dict[str, str] = {}
        for node in oversubscribed:
            baseline = self._get_baseline_ops_per_sec(node)
            if baseline is not None:
                quiet_ratio = oversubscribed_quiet[node.name].min_ops_per_sec / baseline
                self._report_ratio(
                    node,
                    result,
                    test_case_name,
                    "scenario2_min_vs_baseline",
                    quiet_ratio,
                )
                if quiet_ratio < self.STANDARD_PERFORMANCE_FLOOR:
                    failures[f"{node.name} scenario 2"] = (
                        f"{self._get_vm_size(node)} reached {quiet_ratio:.0%} of "
                        f"baseline, expected full speed "
                        f"(>= {self.STANDARD_PERFORMANCE_FLOOR:.0%})"
                    )
            reference = baseline or oversubscribed_quiet[node.name].p50_ops_per_sec
            busy_ratio = all_busy[node.name].min_ops_per_sec / reference
            floor = self._get_performance_floor(node)
            self._report_ratio(
                node, result, test_case_name, "scenario1_min_vs_reference", busy_ratio
            )
            if busy_ratio < floor:
                reference_name = "baseline" if baseline else "scenario 2 median"
                failures[f"{node.name} scenario 1"] = (
                    f"{self._get_vm_size(node)} reached {busy_ratio:.0%} of its "
                    f"{reference_name}, floor {floor:.0%}"
                )
        for node in standard:
            busy_ratio = (
                all_busy[node.name].min_ops_per_sec
                / standard_alone[node.name].p50_ops_per_sec
            )
            self._report_ratio(
                node, result, test_case_name, "scenario1_min_vs_alone", busy_ratio
            )
            if busy_ratio < self.STANDARD_PERFORMANCE_FLOOR:
                failures[f"{node.name} scenario 1"] = (
                    f"{self._get_vm_size(node)} reached {busy_ratio:.0%} of its "
                    f"speed with oversubscribed VMs idle, expected no degradation "
                    f"(>= {self.STANDARD_PERFORMANCE_FLOOR:.0%})"
                )

        self._assert_no_new_kernel_errors(nodes, errors_before)
        assert_that(failures).described_as(
            "overpacking scenario expectations were not met. Confirm all VMs "
            "were on the same packed node, then review host contention."
        ).is_empty()

    @TestCaseMetadata(
        description="""
        Covers the OK2GoLive requirement that standard VMs on a packed node see
        no network or storage degradation when oversubscribed VMs (DTv7/DTav7/
        Asv3) are busy. The environment must contain at least one
        oversubscribed VM and one standard VM on the same packed node (for
        example a single-node TIP session); otherwise the test is skipped.

        Measures, with oversubscribed VMs idle and then with them running
        stress-ng on all vCPUs:
        - storage: fio 4K random read IOPS on a file on the first standard VM.
        - network: iperf3 TCP throughput between the first two standard VMs
          (only if there are at least two).
        Fails if either measurement under load drops below 90% of its idle
        value.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_io_standard_vm_under_oversubscribed_load(
        self,
        environment: Environment,
        log: Logger,
        result: TestResult,
    ) -> None:
        test_case_name = "perf_io_standard_vm_under_oversubscribed_load"
        nodes = list(environment.nodes.list())
        oversubscribed, standard = self._split_by_oversubscription(nodes)
        # iperf3 stops the firewall and fio leaves files; later cases need a
        # clean VM.
        for node in standard:
            node.mark_dirty()
        network_pair = standard[:2] if len(standard) >= 2 else []
        if not network_pair:
            log.info(
                "only one standard VM in the environment, skipping the network "
                "measurement; storage is still measured"
            )

        log.info("measuring standard-VM I/O with oversubscribed VMs idle")
        idle = self._measure_standard_io(standard[0], network_pair, log)

        log.info(
            f"measuring standard-VM I/O with {len(oversubscribed)} "
            f"oversubscribed VMs busy"
        )
        # Two sequential measurements plus margin for tool startup.
        load_seconds = self.IO_MEASURE_SECONDS * 2 + 300
        stress_processes = [
            node.tools[StressNg].launch_cpu_async(
                num_cores=node.tools[Lscpu].get_thread_count(),
                timeout_in_seconds=load_seconds,
            )
            for node in oversubscribed
        ]
        try:
            busy = self._measure_standard_io(standard[0], network_pair, log)
        finally:
            for process in stress_processes:
                if process.is_running():
                    process.kill()

        failures: Dict[str, str] = {}
        for name, unit in (("storage_iops", "IOPS"), ("network_gbps", "Gbps")):
            if name not in idle:
                continue
            ratio = busy[name] / idle[name] if idle[name] else 0.0
            for metric_name, value, metric_unit in (
                (f"{name}_oversubscribed_idle", idle[name], unit),
                (f"{name}_oversubscribed_busy", busy[name], unit),
                (f"{name}_busy_vs_idle_ratio", ratio, ""),
            ):
                send_unified_perf_message(
                    node=standard[0],
                    test_result=result,
                    test_case_name=test_case_name,
                    metric_name=metric_name,
                    metric_value=value,
                    metric_unit=metric_unit,
                    metric_relativity=MetricRelativity.HigherIsBetter,
                    tool="fio" if name == "storage_iops" else "iperf3",
                )
            log.info(
                f"standard-VM {name} on '{standard[0].name}': idle "
                f"{idle[name]:.2f} {unit}, oversubscribed busy {busy[name]:.2f} "
                f"{unit}, ratio {ratio:.3f}"
            )
            if ratio < self.STANDARD_PERFORMANCE_FLOOR:
                failures[name] = (
                    f"{ratio:.0%} of idle value, expected no degradation "
                    f"(>= {self.STANDARD_PERFORMANCE_FLOOR:.0%})"
                )
        assert_that(failures).described_as(
            "standard-VM I/O degraded while oversubscribed VMs were busy. "
            "Confirm all VMs were on the same packed node, then review host "
            "network and storage contention."
        ).is_empty()

    def _split_by_oversubscription(
        self, nodes: List[Node]
    ) -> Tuple[List[Node], List[Node]]:
        oversubscribed = [node for node in nodes if self._is_oversubscribed(node)]
        standard = [node for node in nodes if not self._is_oversubscribed(node)]
        if not oversubscribed or not standard:
            sizes = sorted({self._get_vm_size(node) for node in nodes})
            raise SkippedException(
                f"needs at least one oversubscribed (DTv7/DTav7/Asv3) VM and one "
                f"standard VM in the same environment, got sizes {sizes}. Deploy "
                f"a mixed-size environment onto a single packed node, e.g. a "
                f"single-node TIP session."
            )
        return oversubscribed, standard

    def _is_oversubscribed(self, node: Node) -> bool:
        vm_size = self._get_vm_size(node)
        return bool(
            self._dt_size_pattern.match(vm_size)
            or self._a_series_size_pattern.match(vm_size)
        )

    def _run_cpu_phase(
        self,
        nodes: List[Node],
        log: Logger,
        result: TestResult,
        test_case_name: str,
        metric_prefix: str,
    ) -> Dict[str, _CpuWindowResult]:
        node_results = run_in_parallel(
            [
                partial(
                    self._run_cpu_windows_and_report,
                    node=node,
                    log=log,
                    result=result,
                    test_case_name=test_case_name,
                    baseline_ops_per_sec=None,
                    window_count=self.MIXED_PHASE_WINDOW_COUNT,
                    metric_prefix=metric_prefix,
                )
                for node in nodes
            ],
            log,
        )
        return {
            node.name: node_result for node, node_result in zip(nodes, node_results)
        }

    def _report_ratio(
        self,
        node: Node,
        result: TestResult,
        test_case_name: str,
        metric_name: str,
        ratio: float,
    ) -> None:
        send_unified_perf_message(
            node=node,
            test_result=result,
            test_case_name=test_case_name,
            metric_name=metric_name,
            metric_value=ratio,
            metric_relativity=MetricRelativity.HigherIsBetter,
            tool="stress-ng",
        )

    def _assert_no_new_kernel_errors(
        self, nodes: List[Node], errors_before: Dict[str, List[str]]
    ) -> None:
        new_errors: Dict[str, List[str]] = {}
        for node in nodes:
            errors_after = self._get_kernel_error_lines(node.tools[Dmesg])
            node_new_errors = list(
                (Counter(errors_after) - Counter(errors_before[node.name])).elements()
            )
            if node_new_errors:
                new_errors[node.name] = node_new_errors
        assert_that(new_errors).described_as(
            "one or more VMs reported kernel stability errors during CPU load. "
            "Review host contention for those VMs and reproduce on the "
            "corresponding base VM size."
        ).is_empty()

    def _measure_standard_io(
        self, storage_node: Node, network_pair: List[Node], log: Logger
    ) -> Dict[str, float]:
        measurements = {"storage_iops": self._measure_storage_iops(storage_node)}
        if network_pair:
            measurements["network_gbps"] = self._measure_network_gbps(
                client=network_pair[0], server=network_pair[1]
            )
        log.debug(f"standard-VM I/O measurements: {measurements}")
        return measurements

    def _measure_storage_iops(self, node: Node) -> float:
        filename = "cpu_oversub_fiodata"
        try:
            fio_result = node.tools[Fio].launch(
                name="cpu_oversub_storage",
                filename=filename,
                mode="randread",
                iodepth=self.FIO_IODEPTH,
                numjob=node.tools[Lscpu].get_thread_count(),
                time=self.IO_MEASURE_SECONDS,
                block_size="4K",
                # Fio passes size_gb as "--size=<n>M", so 1024 means a 1 GiB file.
                size_gb=1024,
                overwrite=True,
                time_based=True,
            )
        finally:
            data_path = node.get_pure_path(filename)
            if node.shell.exists(data_path):
                node.shell.remove(data_path)
        return float(fio_result.iops)

    def _measure_network_gbps(self, client: Node, server: Node) -> float:
        server.tools[Iperf3].run_as_server_async()
        try:
            client_result = client.tools[Iperf3].run_as_client(
                server_ip=cast(RemoteNode, server).internal_address,
                report_unit="g",
                run_time_seconds=self.IO_MEASURE_SECONDS,
                parallel_number=self.IPERF3_PARALLEL_STREAMS,
            )
        finally:
            server.tools[Kill].by_name("iperf3")
        return float(client.tools[Iperf3].get_sender_bandwidth(client_result.stdout))

    def _run_cpu_windows_and_report(
        self,
        node: Node,
        log: Logger,
        result: TestResult,
        test_case_name: str,
        baseline_ops_per_sec: Optional[float],
        window_count: Optional[int] = None,
        metric_prefix: str = "",
    ) -> _CpuWindowResult:
        """
        Runs back-to-back cpu windows on all vCPUs of the node and publishes the
        metrics, prefixed with metric_prefix. Uses WINDOW_COUNT windows unless
        window_count is given.
        """
        window_count = window_count or self.WINDOW_COUNT
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
                f"cpu oversubscription {metric_prefix}window "
                f"{index + 1}/{window_count} on "
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
                metric_name=f"{metric_prefix}{name}",
                metric_value=value,
                metric_unit=unit,
                metric_relativity=relativity,
                tool="stress-ng",
            )
        metric_summary = ", ".join(
            f"{name}={value:.3f}{unit}" for name, (value, unit) in metrics.items()
        )
        log.info(
            f"cpu oversubscription {metric_prefix}summary on '{node.name}' "
            f"({thread_count} vCPUs, "
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
        return _CpuWindowResult(
            min_to_peak_ratio=min_to_peak_ratio,
            baseline_ratio=baseline_ratio,
            p50_ops_per_sec=self._percentile(throughputs, 50),
            min_ops_per_sec=min(throughputs),
        )

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
