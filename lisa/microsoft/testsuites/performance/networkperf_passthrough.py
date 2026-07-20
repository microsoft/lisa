# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from decimal import Decimal
from functools import partial
from pathlib import Path
from statistics import median
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union, cast

from assertpy import assert_that
from microsoft.testsuites.performance.common import (
    perf_iperf,
    perf_ntttcp,
    perf_tcp_pps,
)

from lisa import (
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    node_requirement,
    notifier,
    schema,
    search_space,
    simple_requirement,
)
from lisa.environment import Environment, Node
from lisa.features import StartStop
from lisa.messages import (
    MetricRelativity,
    NetworkTCPPerformanceMessage,
    NetworkUDPPerformanceMessage,
    send_unified_perf_message,
)
from lisa.operating_system import Windows
from lisa.sut_orchestrator import CLOUD_HYPERVISOR, HYPERV, OPENVMM
from lisa.testsuite import TestResult
from lisa.tools import Dhclient, Ethtool, Kill, PowerShell, Sysctl
from lisa.tools.ip import Ip
from lisa.tools.iperf3 import (
    IPERF_TCP_BUFFER_LENGTHS,
    IPERF_TCP_CONCURRENCY,
    IPERF_UDP_BUFFER_LENGTHS,
    IPERF_UDP_CONCURRENCY,
)
from lisa.tools.ntttcp import NTTTCP_TCP_CONCURRENCY, NTTTCP_UDP_CONCURRENCY, Ntttcp
from lisa.util import (
    LisaException,
    SkippedException,
    check_till_timeout,
    constants,
    find_group_in_lines,
)
from lisa.util.logger import get_logger
from lisa.util.parallel import run_in_parallel
from lisa.util.shell import wait_tcp_port_ready

SUPPORTED_PASSTHROUGH_PLATFORMS = [CLOUD_HYPERVISOR, HYPERV, OPENVMM]
WINDOWS_NTTTCP_MAX_SERVER_THREADS = 64
WINDOWS_NTTTCP_MAX_MIXED_TCP_CONNECTIONS = 512
WINDOWS_NTTTCP_RECEIVER_WAIT_TIMEOUT = 90
# Three matched sweeps dampen transient throughput variation without hiding a
# consistently slow passthrough path.
PASSTHROUGH_MEASUREMENT_RUN_COUNT = 3
PASSTHROUGH_BASELINE_THRESHOLD = Decimal("0.95")
PASSTHROUGH_BASELINE_THRESHOLD_PERCENT = PASSTHROUGH_BASELINE_THRESHOLD * Decimal(100)
# Target above line rate so UDP iperf saturates the NIC instead of using its
# default 1 Mbit/s UDP bitrate.
PASSTHROUGH_IPERF_UDP_BITRATE_MULTIPLIER = Decimal("1.10")
PASSTHROUGH_HOST_BASELINE_METRIC_NAME = "passthrough_host_baseline_gbps"
PASSTHROUGH_GUEST_MEDIAN_METRIC_NAME = "passthrough_guest_median_gbps"
PASSTHROUGH_BASELINE_PERCENT_METRIC_NAME = "passthrough_baseline_percent"
PASSTHROUGH_GUEST_TO_PEER = "guest-to-peer"
PASSTHROUGH_PEER_TO_GUEST = "peer-to-guest"
# Native-driver reattachment and guest SSH normally complete well inside these
# bounds; exceeding them indicates a device or boot failure worth surfacing.
PASSTHROUGH_HOST_NIC_REBIND_TIMEOUT_SECONDS = 60
PASSTHROUGH_GUEST_START_TIMEOUT_SECONDS = 300
# perf_ntttcp changes TasksMax and may reboot its client at 20,480 connections.
# The immediate Linux virtualization host must remain running during calibration.
PASSTHROUGH_NTTTCP_MAX_CONNECTIONS_WITHOUT_HOST_REBOOT = 10240
NetworkThroughputMessage = Union[
    NetworkTCPPerformanceMessage, NetworkUDPPerformanceMessage
]
ThroughputProfile = Tuple[str, str, int, Decimal]
ThroughputProfileMedian = Tuple[Decimal, NetworkThroughputMessage]
PassthroughBenchmark = Callable[
    [Node, str, Node, str, Optional[ThroughputProfile]],
    List[NetworkThroughputMessage],
]


def _to_decimal(value: Union[Decimal, float, int]) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _get_median_throughput_by_profile(
    runs: List[List[NetworkThroughputMessage]],
) -> Dict[ThroughputProfile, ThroughputProfileMedian]:
    samples: Dict[
        ThroughputProfile, List[Tuple[Decimal, NetworkThroughputMessage]]
    ] = {}
    for run_index, messages in enumerate(runs, start=1):
        profiles_in_run: Set[ThroughputProfile] = set()
        for message in messages:
            throughput_gbps = _get_delivered_throughput(message)
            if throughput_gbps <= 0:
                continue
            profile = _get_throughput_profile(message)
            if profile in profiles_in_run:
                raise LisaException(
                    f"Throughput run [{run_index}] reported duplicate profile "
                    f"[{_format_throughput_profile(profile)}]."
                )
            profiles_in_run.add(profile)
            samples.setdefault(profile, []).append((throughput_gbps, message))

    medians: Dict[ThroughputProfile, ThroughputProfileMedian] = {}
    for profile, profile_samples in samples.items():
        if len(profile_samples) != len(runs):
            raise LisaException(
                f"Throughput profile [{_format_throughput_profile(profile)}] "
                f"reported [{len(profile_samples)}] samples across [{len(runs)}] "
                "runs. Verify every matched sweep completes."
            )
        median_gbps = median(sample[0] for sample in profile_samples)
        medians[profile] = (median_gbps, profile_samples[0][1])
    return medians


def _get_throughput_profile(
    message: NetworkThroughputMessage,
) -> ThroughputProfile:
    if isinstance(message, NetworkUDPPerformanceMessage):
        buffer_size = _to_decimal(message.send_buffer_size)
    elif message.buffer_size_bytes > 0:
        buffer_size = _to_decimal(message.buffer_size_bytes)
    else:
        buffer_size = _to_decimal(message.buffer_size)
    return (
        message.tool,
        str(message.protocol_type or ""),
        message.connections_num,
        buffer_size,
    )


def _get_delivered_throughput(
    message: NetworkThroughputMessage,
) -> Decimal:
    if isinstance(message, NetworkUDPPerformanceMessage):
        return _to_decimal(message.rx_throughput_in_gbps)
    if message.rx_throughput_in_gbps > 0:
        return _to_decimal(message.rx_throughput_in_gbps)
    if message.throughput_in_gbps > 0:
        return _to_decimal(message.throughput_in_gbps)
    return _to_decimal(message.tx_throughput_in_gbps)


def _format_throughput_profile(profile: ThroughputProfile) -> str:
    tool, protocol, connections, buffer_size = profile
    return (
        f"tool={tool}, protocol={protocol}, connections={connections}, "
        f"buffer={buffer_size}"
    )


def _select_best_throughput_profile(
    messages: List[NetworkThroughputMessage],
) -> ThroughputProfile:
    medians = _get_median_throughput_by_profile([messages])
    if not medians:
        raise LisaException(
            "The passthrough baseline tuning sweep did not report any delivered "
            "Gbps samples. Verify the remote peer and test NIC data path."
        )
    return max(medians.items(), key=lambda item: item[1][0])[0]


def _filter_throughput_profile(
    messages: List[NetworkThroughputMessage],
    profile: ThroughputProfile,
) -> List[NetworkThroughputMessage]:
    matching = [
        message for message in messages if _get_throughput_profile(message) == profile
    ]
    if len(matching) != 1:
        raise LisaException(
            f"Expected exactly one throughput sample for matched profile "
            f"[{_format_throughput_profile(profile)}], found [{len(matching)}]."
        )
    return matching


@TestSuiteMetadata(
    area="network passthrough",
    category="performance",
    description="""
    This test suite is to validate linux network performance
    for various NIC passthrough scenarios. Measured host-to-guest cases compare
    Linux L2 against the immediate Linux virtualization host using the same NIC,
    independent remote peer, direction, and tool profile. Guest-to-guest cases
    publish performance measurements without enforcing a baseline threshold.
    """,
    requirement=simple_requirement(
        supported_platform_type=SUPPORTED_PASSTHROUGH_PLATFORMS,
        unsupported_os=[Windows],
    ),
)
class NetworkPerformance(TestSuite):
    # Timeout values:
    # TIMEOUT: 12000s (3.3 hrs) - accounts for test execution + network setup overhead
    # PPS_TIMEOUT: 3000s (50 min) - shorter for PPS tests which are less intensive
    TIMEOUT = 12000
    PPS_TIMEOUT = 3000
    NTTTCP_TCP_CLIENT_TIMEOUT_TOLERANCE_SECONDS = 180  # High-fanout TCP drain.

    # Track baremetal host nodes for cleanup
    _baremetal_hosts: List[RemoteNode] = []
    _link_speed_pattern = re.compile(
        r"^(?P<speed>\d+(?:\.\d+)?)\s*(?P<unit>[GM](?:b/s|bps))$",
        re.IGNORECASE,
    )

    def _assert_passthrough_baseline(
        self,
        test_result: TestResult,
        baseline_runs: List[List[NetworkThroughputMessage]],
        guest_runs: List[List[NetworkThroughputMessage]],
        direction: str,
        guest: RemoteNode,
        guest_nic_name: str,
        host: Node,
        host_nic_name: str,
        peer: RemoteNode,
        peer_nic_name: str,
    ) -> str:
        baseline_medians = _get_median_throughput_by_profile(baseline_runs)
        guest_medians = _get_median_throughput_by_profile(guest_runs)
        if not baseline_medians:
            raise LisaException(
                f"No host throughput samples were reported for passthrough "
                f"baseline validation in direction [{direction}]."
            )

        profile, (baseline_gbps, _) = max(
            baseline_medians.items(), key=lambda item: item[1][0]
        )
        guest_profile = guest_medians.get(profile)
        if guest_profile is None:
            raise LisaException(
                f"Guest throughput did not report the host's best matched profile "
                f"[{_format_throughput_profile(profile)}] in direction "
                f"[{direction}]. Verify host and guest runs use identical tool "
                "parameters."
            )

        guest_gbps, guest_message = guest_profile
        threshold_gbps = baseline_gbps * PASSTHROUGH_BASELINE_THRESHOLD
        baseline_percent = guest_gbps / baseline_gbps * Decimal(100)
        profile_description = _format_throughput_profile(profile)
        result_summary = (
            f"Passthrough {direction}: guest median {guest_gbps:.2f} Gbps "
            f"({baseline_percent:.2f}% of Linux-host median "
            f"{baseline_gbps:.2f} Gbps), threshold {threshold_gbps:.2f} Gbps, "
            f"profile [{profile_description}]"
        )
        guest.log.info(
            f"Passthrough measured-baseline summary for "
            f"{guest_message.test_case_name}: direction={direction}, "
            f"host_median={baseline_gbps} Gbps, guest_median={guest_gbps} Gbps, "
            f"baseline_percent={baseline_percent}%, "
            f"threshold={threshold_gbps} Gbps, profile=[{profile_description}], "
            f"host_nic={host.name}:{host_nic_name}, "
            f"guest_nic={guest.name}:{guest_nic_name}, "
            f"peer_nic={peer.name}:{peer_nic_name}"
        )
        metric_suffix = direction.replace("-", "_")
        for metric_name, metric_value, metric_relativity, metric_description in [
            (
                f"{PASSTHROUGH_HOST_BASELINE_METRIC_NAME}_{metric_suffix}",
                baseline_gbps,
                MetricRelativity.Parameter,
                "Median throughput measured on the immediate Linux host before "
                "passing the NIC to the guest.",
            ),
            (
                f"{PASSTHROUGH_GUEST_MEDIAN_METRIC_NAME}_{metric_suffix}",
                guest_gbps,
                MetricRelativity.HigherIsBetter,
                "Median guest throughput for the matched host baseline profile.",
            ),
            (
                f"{PASSTHROUGH_BASELINE_PERCENT_METRIC_NAME}_{metric_suffix}",
                baseline_percent,
                MetricRelativity.HigherIsBetter,
                "Guest median throughput as a percentage of the immediate "
                "Linux-host baseline.",
            ),
        ]:
            send_unified_perf_message(
                node=guest,
                test_result=test_result,
                test_case_name=guest_message.test_case_name,
                metric_name=metric_name,
                metric_value=float(metric_value),
                metric_unit=("%" if "percent" in metric_name else "Gbps"),
                metric_description=metric_description,
                metric_relativity=metric_relativity,
                tool=guest_message.tool,
                protocol_type=guest_message.protocol_type,
            )

        assert_that(guest_gbps).described_as(
            f"Guest median throughput [{guest_gbps} Gbps] in direction "
            f"[{direction}] must be at least "
            f"{PASSTHROUGH_BASELINE_THRESHOLD_PERCENT:.0f}% of the immediate "
            f"Linux-host median [{baseline_gbps} Gbps], threshold "
            f"[{threshold_gbps} Gbps], profile [{profile_description}]."
        ).is_greater_than_or_equal_to(threshold_gbps)
        return result_summary

    def _run_measured_passthrough_benchmark(
        self,
        node: Node,
        test_result: TestResult,
        log_path: Path,
        variables: Dict[str, Any],
        benchmark: PassthroughBenchmark,
    ) -> None:
        guest = cast(RemoteNode, node)
        peer = self._get_passthrough_peer(variables)
        host = self._get_linux_passthrough_host(test_result, node, peer)
        peer_nic_name = self._get_host_nic_name(peer)
        self._validate_physical_pci_nic(peer, peer_nic_name, "remote peer")
        start_stop = node.features[StartStop]
        host_with_address = cast(Any, host)
        had_host_internal_address = hasattr(host, "internal_address")
        original_host_internal_address = getattr(host, "internal_address", "")

        guest_stopped = False
        host_nic_name = ""
        try:
            start_stop.stop()
            guest_stopped = True
            host, host_nic_name = self._configure_passthrough_nic_for_host(node, host)
            self._validate_physical_pci_nic(
                host, host_nic_name, "immediate virtualization host"
            )
            baseline_runs, profiles = self._collect_host_baseline_runs(
                benchmark=benchmark,
                host=host,
                host_nic_name=host_nic_name,
                peer=peer,
                peer_nic_name=peer_nic_name,
            )
        finally:
            try:
                if host_nic_name:
                    self._release_passthrough_host_dhcp(host, host_nic_name)
            finally:
                if had_host_internal_address:
                    host_with_address.internal_address = original_host_internal_address
                elif hasattr(host, "internal_address"):
                    del host_with_address.internal_address
                if guest_stopped:
                    start_stop.start()
                    self._wait_for_guest_start(guest)

        guest, guest_nic_name = self._configure_passthrough_nic_for_node(node, log_path)
        guest_runs = self._collect_guest_throughput_runs(
            benchmark=benchmark,
            guest=guest,
            guest_nic_name=guest_nic_name,
            peer=peer,
            peer_nic_name=peer_nic_name,
            profiles=profiles,
        )
        result_summaries: List[str] = []
        for direction in [PASSTHROUGH_GUEST_TO_PEER, PASSTHROUGH_PEER_TO_GUEST]:
            result_summaries.append(
                self._assert_passthrough_baseline(
                    test_result=test_result,
                    baseline_runs=baseline_runs[direction],
                    guest_runs=guest_runs[direction],
                    direction=direction,
                    guest=guest,
                    guest_nic_name=guest_nic_name,
                    host=host,
                    host_nic_name=host_nic_name,
                    peer=peer,
                    peer_nic_name=peer_nic_name,
                )
            )
        test_result.set_status(test_result.status, " | ".join(result_summaries))

    def _collect_host_baseline_runs(
        self,
        benchmark: PassthroughBenchmark,
        host: Node,
        host_nic_name: str,
        peer: RemoteNode,
        peer_nic_name: str,
    ) -> Tuple[
        Dict[str, List[List[NetworkThroughputMessage]]],
        Dict[str, ThroughputProfile],
    ]:
        host.log.info(
            f"Starting passthrough baseline tuning sweep from "
            f"{host.name}:{host_nic_name} to {peer.name}:{peer_nic_name}"
        )
        guest_to_peer_sweep = benchmark(host, host_nic_name, peer, peer_nic_name, None)
        host.log.info(
            f"Starting passthrough baseline tuning sweep from "
            f"{peer.name}:{peer_nic_name} to {host.name}:{host_nic_name}"
        )
        peer_to_guest_sweep = benchmark(peer, peer_nic_name, host, host_nic_name, None)
        profiles = {
            PASSTHROUGH_GUEST_TO_PEER: _select_best_throughput_profile(
                guest_to_peer_sweep
            ),
            PASSTHROUGH_PEER_TO_GUEST: _select_best_throughput_profile(
                peer_to_guest_sweep
            ),
        }
        runs = {
            PASSTHROUGH_GUEST_TO_PEER: [
                _filter_throughput_profile(
                    guest_to_peer_sweep, profiles[PASSTHROUGH_GUEST_TO_PEER]
                )
            ],
            PASSTHROUGH_PEER_TO_GUEST: [
                _filter_throughput_profile(
                    peer_to_guest_sweep, profiles[PASSTHROUGH_PEER_TO_GUEST]
                )
            ],
        }

        for run_number in range(2, PASSTHROUGH_MEASUREMENT_RUN_COUNT + 1):
            host.log.info(
                f"Running Linux-host passthrough baseline sample "
                f"{run_number}/{PASSTHROUGH_MEASUREMENT_RUN_COUNT}"
            )
            runs[PASSTHROUGH_GUEST_TO_PEER].append(
                benchmark(
                    host,
                    host_nic_name,
                    peer,
                    peer_nic_name,
                    profiles[PASSTHROUGH_GUEST_TO_PEER],
                )
            )
            runs[PASSTHROUGH_PEER_TO_GUEST].append(
                benchmark(
                    peer,
                    peer_nic_name,
                    host,
                    host_nic_name,
                    profiles[PASSTHROUGH_PEER_TO_GUEST],
                )
            )
        return runs, profiles

    def _collect_guest_throughput_runs(
        self,
        benchmark: PassthroughBenchmark,
        guest: RemoteNode,
        guest_nic_name: str,
        peer: RemoteNode,
        peer_nic_name: str,
        profiles: Dict[str, ThroughputProfile],
    ) -> Dict[str, List[List[NetworkThroughputMessage]]]:
        runs: Dict[str, List[List[NetworkThroughputMessage]]] = {
            PASSTHROUGH_GUEST_TO_PEER: [],
            PASSTHROUGH_PEER_TO_GUEST: [],
        }
        for run_number in range(1, PASSTHROUGH_MEASUREMENT_RUN_COUNT + 1):
            guest.log.info(
                f"Running guest passthrough throughput sample "
                f"{run_number}/{PASSTHROUGH_MEASUREMENT_RUN_COUNT}"
            )
            runs[PASSTHROUGH_GUEST_TO_PEER].append(
                benchmark(
                    guest,
                    guest_nic_name,
                    peer,
                    peer_nic_name,
                    profiles[PASSTHROUGH_GUEST_TO_PEER],
                )
            )
            runs[PASSTHROUGH_PEER_TO_GUEST].append(
                benchmark(
                    peer,
                    peer_nic_name,
                    guest,
                    guest_nic_name,
                    profiles[PASSTHROUGH_PEER_TO_GUEST],
                )
            )
        return runs

    def _get_iperf_udp_line_rate_bitrate_gbps(
        self,
        client: RemoteNode,
        client_nic_name: str,
        server: RemoteNode,
        server_nic_name: str,
    ) -> Decimal:
        line_rate_gbps = min(
            self._get_link_rate_gbps(client, client_nic_name),
            self._get_link_rate_gbps(server, server_nic_name),
        )
        return line_rate_gbps * PASSTHROUGH_IPERF_UDP_BITRATE_MULTIPLIER

    def _get_link_rate_gbps(self, node: RemoteNode, nic_name: str) -> Decimal:
        if isinstance(node.os, Windows):
            escaped_nic_name = nic_name.replace("'", "''")
            speed = cast(
                str,
                node.tools[PowerShell].run_cmdlet(
                    f"(Get-NetAdapter -Name '{escaped_nic_name}' "
                    "-ErrorAction Stop).LinkSpeed",
                    fail_on_error=False,
                    force_run=True,
                ),
            ).strip()
        else:
            speed = (
                node.tools[Ethtool]
                .get_device_link_settings(nic_name)
                .link_settings.get("Speed", "")
                .strip()
            )
        matched_speed = self._link_speed_pattern.match(speed)
        if not matched_speed:
            raise SkippedException(
                f"Cannot determine line rate for NIC [{node.name}:{nic_name}] "
                f"from link speed value [{speed}]."
            )

        speed_value = Decimal(matched_speed.group("speed"))
        if speed_value <= 0:
            raise SkippedException(
                f"NIC [{node.name}:{nic_name}] reported non-positive link speed "
                f"[{speed}]. Verify the NIC link is up and reports a valid speed "
                "before sizing the passthrough UDP offered load."
            )
        speed_unit = matched_speed.group("unit").lower()
        if speed_unit in ["mb/s", "mbps"]:
            return speed_value / Decimal(1000)
        if speed_unit in ["gb/s", "gbps"]:
            return speed_value
        raise SkippedException(
            f"Unsupported link speed unit [{speed_unit}] for NIC "
            f"[{node.name}:{nic_name}]."
        )

    # Network device passthrough tests between host and guest
    @TestCaseMetadata(
        description="""
        Measure bidirectional TCP iperf throughput on the immediate Linux host,
        pass the same NIC to L2, and require matched L2 medians to reach 95% of
        the host medians. The independent Linux peer is configured with the
        passthrough_peer_* test variables.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=1,
            supported_platform_type=[CLOUD_HYPERVISOR],
            supported_features=[StartStop],
            unsupported_os=[Windows],
        ),
    )
    def perf_tcp_iperf_passthrough_host_guest(
        self,
        node: Node,
        result: TestResult,
        log_path: Path,
        variables: Dict[str, Any],
    ) -> None:
        def run_iperf(
            client: Node,
            client_nic_name: str,
            server: Node,
            server_nic_name: str,
            profile: Optional[ThroughputProfile],
        ) -> List[NetworkThroughputMessage]:
            del client_nic_name, server_nic_name
            connections = [profile[2]] if profile else IPERF_TCP_CONCURRENCY
            buffer_lengths = [int(profile[3])] if profile else IPERF_TCP_BUFFER_LENGTHS
            messages: List[NetworkThroughputMessage] = perf_iperf(
                test_result=result,
                connections=connections,
                buffer_length_list=buffer_lengths,
                server=cast(RemoteNode, server),
                client=cast(RemoteNode, client),
                run_with_internal_address=True,
                test_case_name="perf_tcp_iperf_passthrough_host_guest",
            )
            return messages

        self._run_measured_passthrough_benchmark(
            node=node,
            test_result=result,
            log_path=log_path,
            variables=variables,
            benchmark=run_iperf,
        )

    @TestCaseMetadata(
        description="""
        Measure bidirectional UDP iperf throughput on the immediate Linux host,
        pass the same NIC to L2, and require matched L2 medians to reach 95% of
        the host medians. The independent Linux peer is configured with the
        passthrough_peer_* test variables.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=1,
            supported_platform_type=[CLOUD_HYPERVISOR],
            supported_features=[StartStop],
            unsupported_os=[Windows],
        ),
    )
    def perf_udp_iperf_passthrough_host_guest(
        self,
        node: Node,
        result: TestResult,
        log_path: Path,
        variables: Dict[str, Any],
    ) -> None:
        udp_bitrate_gbps: Optional[Decimal] = None

        def run_iperf(
            client: Node,
            client_nic_name: str,
            server: Node,
            server_nic_name: str,
            profile: Optional[ThroughputProfile],
        ) -> List[NetworkThroughputMessage]:
            nonlocal udp_bitrate_gbps
            if udp_bitrate_gbps is None:
                udp_bitrate_gbps = self._get_iperf_udp_line_rate_bitrate_gbps(
                    cast(RemoteNode, client),
                    client_nic_name,
                    cast(RemoteNode, server),
                    server_nic_name,
                )
            connections = [profile[2]] if profile else IPERF_UDP_CONCURRENCY
            buffer_lengths = [int(profile[3])] if profile else IPERF_UDP_BUFFER_LENGTHS
            messages: List[NetworkThroughputMessage] = perf_iperf(
                test_result=result,
                connections=connections,
                buffer_length_list=buffer_lengths,
                server=cast(RemoteNode, server),
                client=cast(RemoteNode, client),
                udp_mode=True,
                udp_total_bitrate_gbps=udp_bitrate_gbps,
                run_with_internal_address=True,
                test_case_name="perf_udp_iperf_passthrough_host_guest",
            )
            return messages

        self._run_measured_passthrough_benchmark(
            node=node,
            test_result=result,
            log_path=log_path,
            variables=variables,
            benchmark=run_iperf,
        )

    @TestCaseMetadata(
        description="""
        This test case uses sar to test passthrough network PPS (Packets Per Second)
        when running netperf with single port. Test will consider VM as
        client node and physical host as server node.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=1,
            supported_platform_type=SUPPORTED_PASSTHROUGH_PLATFORMS,
            unsupported_os=[Windows],
        ),
    )
    def perf_tcp_single_pps_passthrough_host_guest(
        self,
        result: TestResult,
        node: Node,
        log_path: Path,
        variables: Dict[str, Any],
    ) -> None:
        server = self._get_host_as_server(variables)
        self._skip_if_windows_server(server, "netperf/sar")

        # Reboot guest into fresh state; never reboot the baremetal host.
        cast(RemoteNode, node).reboot()

        client, _ = self._configure_passthrough_nic_for_node(
            node, log_path, host_node=server
        )

        perf_tcp_pps(
            test_result=result,
            test_type="singlepps",
            server=server,
            client=client,
            use_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses sar to test passthrough network PPS (Packets Per Second)
        when running netperf with multiple ports. Run netperf client on VM
        and server on physical host.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=1,
            supported_platform_type=SUPPORTED_PASSTHROUGH_PLATFORMS,
            unsupported_os=[Windows],
        ),
    )
    def perf_tcp_max_pps_passthrough_host_guest(
        self,
        result: TestResult,
        node: Node,
        log_path: Path,
        variables: Dict[str, Any],
    ) -> None:
        server = self._get_host_as_server(variables)
        self._skip_if_windows_server(server, "netperf/sar")

        # Reboot guest into fresh state; never reboot the baremetal host.
        cast(RemoteNode, node).reboot()

        client, _ = self._configure_passthrough_nic_for_node(
            node, log_path, host_node=server
        )

        perf_tcp_pps(
            test_result=result,
            test_type="maxpps",
            server=server,
            client=client,
            use_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        Measure bidirectional TCP NTTTCP throughput on the immediate Linux host,
        pass the same NIC to L2, and require matched L2 medians to reach 95% of
        the host medians. The independent Linux peer is configured with the
        passthrough_peer_* test variables.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=1,
                memory_mb=search_space.IntRange(min=8192),
            ),
            supported_platform_type=[CLOUD_HYPERVISOR],
            supported_features=[StartStop],
        ),
    )
    def perf_tcp_ntttcp_passthrough_host_guest(
        self,
        result: TestResult,
        node: Node,
        log_path: Path,
        variables: Dict[str, Any],
    ) -> None:
        tcp_connections = [
            connection
            for connection in NTTTCP_TCP_CONCURRENCY
            if connection <= PASSTHROUGH_NTTTCP_MAX_CONNECTIONS_WITHOUT_HOST_REBOOT
        ]

        def run_ntttcp(
            client: Node,
            client_nic_name: str,
            server: Node,
            server_nic_name: str,
            profile: Optional[ThroughputProfile],
        ) -> List[NetworkThroughputMessage]:
            connections = [profile[2]] if profile else tcp_connections
            messages: List[NetworkThroughputMessage] = perf_ntttcp(
                test_result=result,
                client=cast(RemoteNode, client),
                server=cast(RemoteNode, server),
                connections=connections,
                test_case_name="perf_tcp_ntttcp_passthrough_host_guest",
                server_nic_name=server_nic_name,
                client_nic_name=client_nic_name,
                skip_server_task_max=True,
                client_ntttcp_timeout_tolerance_seconds=(
                    self.NTTTCP_TCP_CLIENT_TIMEOUT_TOLERANCE_SECONDS
                ),
            )
            return messages

        self._run_measured_passthrough_benchmark(
            node=node,
            test_result=result,
            log_path=log_path,
            variables=variables,
            benchmark=run_ntttcp,
        )

    @TestCaseMetadata(
        description="""
        Measure bidirectional UDP NTTTCP throughput on the immediate Linux host,
        pass the same NIC to L2, and require matched L2 medians to reach 95% of
        the host medians. The independent Linux peer is configured with the
        passthrough_peer_* test variables.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=1,
                memory_mb=search_space.IntRange(min=8192),
            ),
            supported_platform_type=[CLOUD_HYPERVISOR],
            supported_features=[StartStop],
        ),
    )
    def perf_udp_1k_ntttcp_passthrough_host_guest(
        self,
        result: TestResult,
        node: Node,
        log_path: Path,
        variables: Dict[str, Any],
    ) -> None:
        def run_ntttcp(
            client: Node,
            client_nic_name: str,
            server: Node,
            server_nic_name: str,
            profile: Optional[ThroughputProfile],
        ) -> List[NetworkThroughputMessage]:
            connections = [profile[2]] if profile else NTTTCP_UDP_CONCURRENCY
            messages: List[NetworkThroughputMessage] = perf_ntttcp(
                test_result=result,
                client=cast(RemoteNode, client),
                server=cast(RemoteNode, server),
                udp_mode=True,
                connections=connections,
                test_case_name="perf_udp_1k_ntttcp_passthrough_host_guest",
                server_nic_name=server_nic_name,
                client_nic_name=client_nic_name,
                skip_server_task_max=True,
            )
            return messages

        self._run_measured_passthrough_benchmark(
            node=node,
            test_result=result,
            log_path=log_path,
            variables=variables,
            benchmark=run_ntttcp,
        )

    # Network device passthrough tests between 2 guests
    @TestCaseMetadata(
        description="""
        Run TCP iperf between two passthrough guests and publish the measurements
        without enforcing a line-rate or host-baseline threshold.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            supported_platform_type=SUPPORTED_PASSTHROUGH_PLATFORMS,
            unsupported_os=[Windows],
        ),
    )
    def perf_tcp_iperf_passthrough_two_guest(
        self, result: TestResult, log_path: Path
    ) -> None:
        # Run iperf server on VM and client on another VM
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        server_node = cast(RemoteNode, environment.nodes[1])

        # Reboot both guests first to avoid stale passthrough NIC state.
        client_node.reboot()
        server_node.reboot()

        client, _ = self._configure_passthrough_nic_for_node(client_node, log_path)
        server, _ = self._configure_passthrough_nic_for_node(server_node, log_path)

        perf_iperf(
            test_result=result,
            connections=IPERF_TCP_CONCURRENCY,
            buffer_length_list=IPERF_TCP_BUFFER_LENGTHS,
            server=server,
            client=client,
            run_with_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        Run UDP iperf between two passthrough guests and publish the measurements
        without enforcing a line-rate or host-baseline threshold.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            supported_platform_type=SUPPORTED_PASSTHROUGH_PLATFORMS,
            unsupported_os=[Windows],
        ),
    )
    def perf_udp_iperf_passthrough_two_guest(
        self, result: TestResult, log_path: Path
    ) -> None:
        # Run iperf server on VM and client on another VM
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        server_node = cast(RemoteNode, environment.nodes[1])

        # Reboot both nodes; Libvirt may reuse them, boot into fresh state.
        client_node.reboot()
        server_node.reboot()

        client, client_nic_name = self._configure_passthrough_nic_for_node(
            client_node, log_path
        )
        server, server_nic_name = self._configure_passthrough_nic_for_node(
            server_node, log_path
        )

        perf_iperf(
            test_result=result,
            connections=IPERF_UDP_CONCURRENCY,
            buffer_length_list=IPERF_UDP_BUFFER_LENGTHS,
            server=server,
            client=client,
            udp_mode=True,
            udp_total_bitrate_gbps=self._get_iperf_udp_line_rate_bitrate_gbps(
                client, client_nic_name, server, server_nic_name
            ),
            run_with_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses sar to test passthrough network PPS (Packets Per Second)
        when running netperf with single port. Test will consider VM as
        server node and host as client node.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            supported_platform_type=SUPPORTED_PASSTHROUGH_PLATFORMS,
            unsupported_os=[Windows],
        ),
    )
    def perf_tcp_single_pps_passthrough_two_guest(
        self, result: TestResult, log_path: Path
    ) -> None:
        # Run netperf server on VM and client on another VM
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        server_node = cast(RemoteNode, environment.nodes[1])

        # Reboot both nodes; Libvirt may reuse them, boot into fresh state.
        client_node.reboot()
        server_node.reboot()

        client, _ = self._configure_passthrough_nic_for_node(client_node, log_path)
        server, _ = self._configure_passthrough_nic_for_node(server_node, log_path)

        perf_tcp_pps(
            test_result=result,
            test_type="singlepps",
            server=server,
            client=client,
            use_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses sar to test passthrough network PPS (Packets Per Second)
        when running netperf with multiple ports. Test will consider VM as
        server node and host as client node.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            supported_platform_type=SUPPORTED_PASSTHROUGH_PLATFORMS,
            unsupported_os=[Windows],
        ),
    )
    def perf_tcp_max_pps_passthrough_two_guest(
        self, result: TestResult, log_path: Path
    ) -> None:
        # Run netperf server on VM and client on another VM
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        server_node = cast(RemoteNode, environment.nodes[1])

        # Reboot both nodes; Libvirt may reuse them, boot into fresh state.
        client_node.reboot()
        server_node.reboot()

        client, _ = self._configure_passthrough_nic_for_node(client_node, log_path)
        server, _ = self._configure_passthrough_nic_for_node(server_node, log_path)

        perf_tcp_pps(
            test_result=result,
            test_type="maxpps",
            server=server,
            client=client,
            use_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        Run TCP NTTTCP between two passthrough guests and publish the measurements
        without enforcing a line-rate or host-baseline threshold.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=2,
                memory_mb=search_space.IntRange(min=8192),
            ),
            supported_platform_type=SUPPORTED_PASSTHROUGH_PLATFORMS,
        ),
    )
    def perf_tcp_ntttcp_passthrough_two_guest(
        self, result: TestResult, log_path: Path
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        server_node = cast(RemoteNode, environment.nodes[1])

        # Reboot both nodes; Libvirt may reuse them, boot into fresh state.
        client_node.reboot()
        server_node.reboot()

        client, client_nic_name = self._configure_passthrough_nic_for_node(
            client_node, log_path
        )
        server, server_nic_name = self._configure_passthrough_nic_for_node(
            server_node, log_path
        )

        def refresh_passthrough_nics() -> Tuple[Optional[str], Optional[str]]:
            nonlocal client_nic_name, server_nic_name
            _, refreshed_client_nic_name = self._configure_passthrough_nic_for_node(
                client_node, log_path
            )
            _, refreshed_server_nic_name = self._configure_passthrough_nic_for_node(
                server_node, log_path
            )
            client_nic_name = refreshed_client_nic_name
            server_nic_name = refreshed_server_nic_name
            return refreshed_client_nic_name, refreshed_server_nic_name

        perf_ntttcp(
            test_result=result,
            client=client,
            server=server,
            server_nic_name=server_nic_name,
            client_nic_name=client_nic_name,
            post_ntttcp_setup=refresh_passthrough_nics,
            client_ntttcp_timeout_tolerance_seconds=(
                self.NTTTCP_TCP_CLIENT_TIMEOUT_TOLERANCE_SECONDS
            ),
        )

    @TestCaseMetadata(
        description="""
        Run UDP NTTTCP between two passthrough guests and publish the measurements
        without enforcing a line-rate or host-baseline threshold.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=2,
                memory_mb=search_space.IntRange(min=8192),
            ),
            supported_platform_type=SUPPORTED_PASSTHROUGH_PLATFORMS,
        ),
    )
    def perf_udp_1k_ntttcp_passthrough_two_guest(
        self, result: TestResult, log_path: Path
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        server_node = cast(RemoteNode, environment.nodes[1])

        # Reboot both nodes; Libvirt may reuse them, boot into fresh state.
        client_node.reboot()
        server_node.reboot()

        client, client_nic_name = self._configure_passthrough_nic_for_node(
            client_node, log_path
        )
        server, server_nic_name = self._configure_passthrough_nic_for_node(
            server_node, log_path
        )

        perf_ntttcp(
            test_result=result,
            client=client,
            server=server,
            server_nic_name=server_nic_name,
            client_nic_name=client_nic_name,
            udp_mode=True,
        )

    @staticmethod
    def _norm_hex(value: str, width: int) -> str:
        """Zero-pad lowercase hex PCI component; strips leading '0x'."""
        return value.lower().replace("0x", "").zfill(width)

    def _configure_passthrough_nic_for_node(
        self,
        node: Node,
        log_path: Path,
        host_node: Optional[RemoteNode] = None,
    ) -> Tuple[RemoteNode, str]:
        _, device_addr_obj = self._get_passthrough_nic_context(node)
        device_bdf = self._get_device_bdf(device_addr_obj)

        host_nic_name = ""
        if host_node is not None and device_bdf:
            _h = host_node.execute(
                f"ls /sys/bus/pci/devices/{device_bdf}/net/ 2>/dev/null"
                " | head -1 || true",
                sudo=True,
                shell=True,
            ).stdout.strip()
            _parts = _h.split()
            host_nic_name = _parts[0] if _parts else ""

        # Exclude management interface from passthrough NIC selection.
        mgmt_ip_ssh = cast(RemoteNode, node).connection_info[
            constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS
        ]
        mgmt_iface_raw = node.execute(
            cmd=f"ip -4 route get {mgmt_ip_ssh} 2>/dev/null || true",
            sudo=True,
            shell=True,
        ).stdout.strip()
        _m = re.search(r"\bdev\s+(\S+)", mgmt_iface_raw)
        mgmt_iface = _m.group(1) if _m else ""

        # Enumerate PCI-backed interfaces as: "<iface> <driver> <carrier>".
        iface_info_raw = node.execute(
            cmd=(
                "for iface in /sys/class/net/*/; do "
                "iface=$(basename $iface); "
                "[ -e /sys/class/net/$iface/device ] || continue; "
                "drv=$(basename "
                "$(readlink /sys/class/net/$iface/device/driver 2>/dev/null) "
                "2>/dev/null); "
                "carrier=$(cat /sys/class/net/$iface/carrier 2>/dev/null "
                "|| echo 0); "
                'echo "$iface $drv $carrier"; '
                "done"
            ),
            sudo=False,
            shell=True,
        ).stdout.strip()

        interface_name = self._find_guest_passthrough_iface(
            node, mgmt_iface, iface_info_raw
        )

        node.log.debug(f"[passthrough-nic] GUEST iface={interface_name!r}")
        if host_node is not None and host_nic_name:
            host_node.log.debug(
                f"[passthrough-nic] HOST nic={host_nic_name!r} BDF={device_bdf!r}"
            )

        node.execute(
            cmd=f"ip link set {interface_name} up",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Failed to bring up interface {interface_name}"
            ),
        )

        self._wait_for_carrier(node, interface_name)

        # Flush stale address/route state from prior runs.
        node.execute(
            f"ip addr flush dev {interface_name} 2>/dev/null || true",
            sudo=True,
            shell=True,
        )
        node.execute(
            f"ip route flush dev {interface_name} 2>/dev/null || true",
            sudo=True,
            shell=True,
        )

        dhcp_result = self._run_dhcp_on_iface(node, interface_name)
        if dhcp_result.exit_code != 0:
            self._raise_dhcp_failure(
                node, interface_name, dhcp_result, host_node, host_nic_name
            )

        # Wait briefly for IP address assignment.
        node.execute(
            cmd=(
                f"for i in $(seq 1 10); do "
                f"ip -4 -o addr show dev {interface_name} "
                f"| grep -q 'inet ' && break; "
                f"sleep 1; done"
            ),
            sudo=True,
            shell=True,
        )

        err_msg = f"Failed to get interface details for: {interface_name}"
        interface_details = node.execute(
            cmd=f"ip addr show {interface_name}",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=err_msg,
        ).stdout
        ip_regex = re.compile(r"\binet (?P<INTERFACE_IP>\d+\.\d+\.\d+\.\d+)/\d+\b")
        interface_ip = find_group_in_lines(
            lines=interface_details,
            pattern=ip_regex,
            single_line=False,
        )
        passthrough_nic_ip = interface_ip.get("INTERFACE_IP", "")
        if not passthrough_nic_ip:
            raise LisaException(
                f"Failed to get IP for passthrough interface '{interface_name}'. "
                f"Interface details: {interface_details[:200]}"
            )

        test_node = cast(RemoteNode, node)
        test_node.internal_address = passthrough_nic_ip

        return test_node, interface_name

    def _configure_passthrough_nic_for_host(
        self,
        node: Node,
        host: Node,
    ) -> Tuple[Node, str]:
        _, device_addr_obj = self._get_passthrough_nic_context(node)
        device_bdf = self._get_device_bdf(device_addr_obj)
        if not device_bdf:
            raise LisaException(
                "Cannot resolve the selected passthrough NIC BDF on the Linux "
                "host. Verify the Cloud Hypervisor device context contains PCI "
                "domain, bus, slot, and function values."
            )

        def get_native_interface_info() -> str:
            return host.execute(
                cmd=(
                    f'driver=$(basename "$(readlink '
                    f'/sys/bus/pci/devices/{device_bdf}/driver 2>/dev/null)" '
                    "2>/dev/null); "
                    f"for path in /sys/bus/pci/devices/{device_bdf}/net/*; do "
                    '[ -e "$path" ] || continue; '
                    'iface=$(basename "$path"); '
                    'carrier=$(cat "/sys/class/net/$iface/carrier" '
                    "2>/dev/null || echo 0); "
                    'echo "${driver:-none}|$iface|$carrier"; '
                    "done"
                ),
                sudo=True,
                shell=True,
                no_info_log=True,
                no_error_log=True,
            ).stdout.strip()

        interface_info = ""

        def get_native_candidates() -> List[Tuple[bool, str]]:
            candidates: List[Tuple[bool, str]] = []
            for line in interface_info.splitlines():
                parts = line.split("|")
                if len(parts) == 3 and parts[0] not in ["none", "vfio-pci"]:
                    candidates.append((parts[2] == "1", parts[1]))
            return candidates

        def is_native_driver_ready() -> bool:
            nonlocal interface_info
            interface_info = get_native_interface_info()
            return bool(get_native_candidates())

        check_till_timeout(
            is_native_driver_ready,
            timeout_message=(
                f"wait for passthrough NIC [{device_bdf}] to rebind to its "
                "native Linux driver after stopping the guest"
            ),
            timeout=PASSTHROUGH_HOST_NIC_REBIND_TIMEOUT_SECONDS,
        )
        candidates = get_native_candidates()
        candidates.sort(key=lambda item: (not item[0], item[1]))
        if not candidates:
            raise LisaException(
                f"Passthrough NIC [{device_bdf}] did not expose a native Linux "
                f"network interface after stopping the guest. Observed: "
                f"[{interface_info}]. Verify libvirt uses managed='yes'."
            )
        interface_name = candidates[0][1]
        host.log.info(
            f"Using immediate Linux-host NIC [{host.name}:{interface_name}] "
            f"for passthrough baseline; BDF [{device_bdf}]"
        )
        host.execute(
            cmd=f"ip link set {interface_name} up",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Failed to bring up Linux-host baseline NIC [{interface_name}]. "
                "Verify its native driver reattached after the guest stopped."
            ),
        )
        self._wait_for_carrier(host, interface_name)
        host.execute(
            f"ip addr flush dev {interface_name} 2>/dev/null || true; "
            f"ip route flush dev {interface_name} 2>/dev/null || true",
            sudo=True,
            shell=True,
        )
        is_configured = False
        try:
            dhcp_result = self._run_dhcp_on_iface(
                host, interface_name, keep_unmanaged=False
            )
            if dhcp_result.exit_code != 0:
                self._raise_dhcp_failure(host, interface_name, dhcp_result)

            interface_details = host.execute(
                cmd=f"ip -4 -o addr show dev {interface_name} scope global",
                sudo=True,
                shell=True,
            ).stdout
            address_match = re.search(
                r"\binet\s+(?P<ip>\d+(?:\.\d+){3})/", interface_details
            )
            if not address_match:
                raise LisaException(
                    f"Linux-host baseline NIC [{interface_name}] did not receive an "
                    f"IPv4 address. Verify DHCP is available on the physical test "
                    f"network. Interface details: [{interface_details[:500]}]"
                )
            cast(Any, host).internal_address = address_match.group("ip")
            is_configured = True
            return host, interface_name
        finally:
            if not is_configured:
                self._release_passthrough_host_dhcp(host, interface_name)

    def _release_passthrough_host_dhcp(self, host: Node, interface_name: str) -> None:
        dhcp_client = host.tools[Dhclient].command
        self._stop_dhcp_on_iface(host, interface_name, dhcp_client)
        host.execute(
            f"ip addr flush dev {interface_name} 2>/dev/null || true; "
            f"ip route flush dev {interface_name} 2>/dev/null || true",
            sudo=True,
            shell=True,
        )

    def _stop_dhcp_on_iface(
        self, node: Node, interface_name: str, dhcp_client: str
    ) -> None:
        if dhcp_client == "dhcpcd":
            node.execute(
                f"dhcpcd -k {interface_name} 2>/dev/null || true",
                sudo=True,
                shell=True,
            )
            return
        if dhcp_client != "dhclient":
            raise LisaException(
                f"Cannot stop unsupported DHCP client [{dhcp_client}] on "
                f"interface [{interface_name}]. Install dhclient or dhcpcd and "
                "retry the passthrough benchmark."
            )

        dhcp_pid = f"/run/dhclient-{interface_name}.pid"
        dhcp_lease = f"/var/lib/dhcp/dhclient-{interface_name}.leases"
        node.execute(
            f"dhclient -r -pf {dhcp_pid} -lf {dhcp_lease} {interface_name} "
            "2>/dev/null || true",
            sudo=True,
            shell=True,
        )
        node.execute(
            f"if [ -s {dhcp_pid} ]; then "
            f'kill "$(cat {dhcp_pid})" 2>/dev/null || true; fi; '
            f"rm -f {dhcp_pid}",
            sudo=True,
            shell=True,
        )
        node.execute(
            f"pkill -f '[d]hclient.*[[:space:]]{interface_name}"
            "([[:space:]]|$)' 2>/dev/null || true",
            sudo=True,
            shell=True,
        )

    def _get_linux_passthrough_host(
        self,
        test_result: TestResult,
        node: Node,
        peer: RemoteNode,
    ) -> Node:
        environment = test_result.environment
        if environment is None or environment.platform is None:
            raise SkippedException(
                "Measured passthrough validation requires the platform context. "
                "Verify the test runs on Cloud Hypervisor."
            )
        platform = environment.platform
        if platform.type_name() != CLOUD_HYPERVISOR:
            raise SkippedException(
                f"Measured passthrough validation requires an immediate Linux "
                f"virtualization host, but platform [{platform.type_name()}] does "
                "not expose one. Run this case on Cloud Hypervisor hosted by "
                "bare-metal Linux or Linux L1VH."
            )
        host_node = getattr(platform, "host_node", None)
        if not isinstance(host_node, Node) or isinstance(host_node.os, Windows):
            raise SkippedException(
                "Measured passthrough validation requires a Linux host that owns "
                "the NIC before assigning it to L2."
            )
        if not node.features.is_supported(StartStop):
            raise SkippedException(
                "Measured passthrough validation must stop L2 to restore the NIC "
                "to its Linux host, but StartStop is unavailable."
            )

        passthrough_context, _ = self._get_passthrough_nic_context(node)
        if getattr(passthrough_context, "managed", "") != "yes":
            raise SkippedException(
                "Measured passthrough validation requires libvirt "
                "managed='yes' so stopping L2 restores the NIC's native Linux "
                "driver before baseline collection."
            )

        host_addresses = set(
            host_node.execute(
                "hostname -I 2>/dev/null || true",
                shell=True,
                no_info_log=True,
            ).stdout.split()
        )
        if isinstance(host_node, RemoteNode):
            host_addresses.add(
                str(
                    host_node.connection_info.get(
                        constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS, ""
                    )
                )
            )
        peer_addresses = {
            peer.internal_address,
            str(
                peer.connection_info.get(
                    constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS, ""
                )
            ),
        }
        if {address for address in peer_addresses if address} & host_addresses:
            raise SkippedException(
                "The configured passthrough peer resolves to the Linux "
                "virtualization host. Configure an independent remote server; "
                "host-to-guest traffic is not a passthrough baseline."
            )
        return host_node

    def _get_passthrough_nic_context(self, node: Node) -> Tuple[Any, Any]:
        node_context = self._get_passthrough_node_context(node)
        for passthrough_context in node_context.passthrough_devices:
            if passthrough_context.pool_type.value != "pci_net":
                continue
            if not passthrough_context.device_list:
                raise LisaException(
                    "The passthrough NIC context has no selected host devices. "
                    "Verify the PCI NIC device pool contains an available device."
                )
            return passthrough_context, passthrough_context.device_list[0]
        raise SkippedException("No PCI NIC passthrough device is assigned to the node")

    def _wait_for_guest_start(self, guest: RemoteNode) -> None:
        address = guest.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS]
        port = guest.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_PORT]
        is_ready, error_code = wait_tcp_port_ready(
            address,
            port,
            log=guest.log,
            timeout=PASSTHROUGH_GUEST_START_TIMEOUT_SECONDS,
        )
        if not is_ready:
            raise LisaException(
                f"L2 guest [{guest.name}] did not become reachable at "
                f"[{address}:{port}] after restoring passthrough ownership. TCP "
                f"error [{error_code}]. Inspect the guest console and VFIO bind "
                "state on the Linux host."
            )

    def _refresh_passthrough_nic_address(
        self, node: RemoteNode, interface_name: str
    ) -> str:
        node.execute(
            cmd=f"ip link set {interface_name} up",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Failed to bring up interface {interface_name}"
            ),
        )
        self._wait_for_carrier(node, interface_name)

        interface_details = node.execute(
            cmd=f"ip -4 -o addr show dev {interface_name} scope global",
            sudo=True,
            shell=True,
        ).stdout
        ip_regex = re.compile(r"\binet (?P<INTERFACE_IP>\d+\.\d+\.\d+\.\d+)/\d+\b")
        interface_ip = find_group_in_lines(
            lines=interface_details,
            pattern=ip_regex,
            single_line=False,
        )
        passthrough_nic_ip = interface_ip.get("INTERFACE_IP", "")
        if not passthrough_nic_ip:
            dhcp_result = self._run_dhcp_on_iface(node, interface_name)
            if dhcp_result.exit_code != 0:
                self._raise_dhcp_failure(node, interface_name, dhcp_result)
            interface_details = node.execute(
                cmd=f"ip -4 -o addr show dev {interface_name} scope global",
                sudo=True,
                shell=True,
            ).stdout
            interface_ip = find_group_in_lines(
                lines=interface_details,
                pattern=ip_regex,
                single_line=False,
            )
            passthrough_nic_ip = interface_ip.get("INTERFACE_IP", "")
            if not passthrough_nic_ip:
                raise LisaException(
                    f"Failed to refresh IP for passthrough interface "
                    f"'{interface_name}'. Interface details: {interface_details[:200]}"
                )

        node.internal_address = passthrough_nic_ip
        return passthrough_nic_ip

    def _get_passthrough_node_context(self, node: Node) -> Any:
        if node.type_name() == OPENVMM:
            from lisa.sut_orchestrator.openvmm.context import (
                get_node_context as get_openvmm_node_context,
            )

            return get_openvmm_node_context(node)

        try:
            from lisa.sut_orchestrator.libvirt.context import (
                get_node_context as get_libvirt_node_context,
            )

            return get_libvirt_node_context(node)
        except AssertionError:
            from lisa.sut_orchestrator.hyperv.context import (
                get_node_context as get_hyperv_node_context,
            )

            return get_hyperv_node_context(node)

    def _get_device_bdf(self, device_addr_obj: Any) -> str:
        bus = getattr(device_addr_obj, "bus", "")
        slot = getattr(device_addr_obj, "slot", "")
        function = getattr(device_addr_obj, "function", "")
        if not (bus and slot and function):
            return ""

        domain = self._norm_hex(getattr(device_addr_obj, "domain", "") or "0000", 4)
        return (
            f"{domain}:{self._norm_hex(bus, 2)}:"
            f"{self._norm_hex(slot, 2)}.{self._norm_hex(function, 1)}"
        )

    def _find_guest_passthrough_iface(
        self,
        node: Node,
        mgmt_iface: str,
        iface_info_raw: str,
    ) -> str:
        """Select passthrough NIC, preferring non-virtio and carrier-up links."""
        pt_candidates: List[Tuple[bool, str]] = []
        virtio_fallback: List[Tuple[bool, str]] = []
        for _line in iface_info_raw.splitlines():
            _parts = _line.split()
            if not _parts:
                continue
            _iface = _parts[0]
            _drv = _parts[1] if len(_parts) > 1 else ""
            _carrier_up = (_parts[2] == "1") if len(_parts) > 2 else False
            if _iface in (mgmt_iface, "lo"):
                continue
            if _drv.startswith("virtio"):
                virtio_fallback.append((_carrier_up, _iface))
            else:
                pt_candidates.append((_carrier_up, _iface))

        # Fall back to virtio, then prefer link-up interfaces.
        if not pt_candidates:
            pt_candidates = virtio_fallback
        pt_candidates.sort(key=lambda t: (not t[0], t[1]))

        if not pt_candidates:
            raise LisaException(
                f"No passthrough NIC found in guest. "
                f"Management iface: {mgmt_iface!r}, "
                f"Enumerated (iface driver carrier): {iface_info_raw!r}"
            )
        return pt_candidates[0][1]

    def _wait_for_carrier(self, node: Node, interface_name: str) -> None:
        """Wait up to 60 s for link carrier; raise with diagnostics on failure."""
        carrier_result = node.execute(
            cmd=(
                f"timeout 60 sh -c 'until cat /sys/class/net/{interface_name}/carrier"
                f" 2>/dev/null | grep -q 1; do sleep 1; done'"
            ),
            sudo=True,
            shell=True,
        )
        if carrier_result.exit_code == 124:
            _nc_diag = node.execute(
                cmd=(
                    f"echo '--- ethtool ---';"
                    f" ethtool {interface_name} 2>/dev/null || true;"
                    f" echo '--- ip -d link ---';"
                    f" ip -d link show {interface_name} 2>/dev/null || true;"
                    f" echo '--- dmesg ---';"
                    f" dmesg -T 2>/dev/null"
                    f" | grep -E 'no carrier|carrier loss|"
                    f"link up|link down|vfio|{interface_name}'"
                    f" | tail -n 20 || true"
                ),
                sudo=True,
                shell=True,
            ).stdout.strip()
            raise LisaException(
                f"Interface {interface_name} NO-CARRIER after 60 s. "
                f"Physical link is not up — DHCP would fail. Failing fast.\n"
                f"{_nc_diag}"
            )
        elif carrier_result.exit_code != 0:
            raise LisaException(
                f"Failed to check carrier on {interface_name}: "
                f"exit code {carrier_result.exit_code}"
            )

    def _install_dhclient_scripts(
        self,
        node: Node,
        config_script: str,
    ) -> None:
        """Install minimal dhclient hook script for interface IP config."""
        node.execute("mkdir -p /usr/local/bin /var/lib/dhcp", sudo=True, shell=True)
        node.execute(
            f"printf '#!/bin/sh\\n"
            f"pfx=0\\n"
            f"IFS=.\\n"
            f'case "$reason" in\\n'
            f'  BOUND|RENEW|REBIND|REBOOT) _mask="$new_subnet_mask" ;;\\n'
            f'  *)                          _mask="$old_subnet_mask" ;;\\n'
            f"esac\\n"
            f"for _o in $_mask; do\\n"
            f"  case $_o in\\n"
            f"    255) pfx=$((pfx+8)) ;;\\n"
            f"    254) pfx=$((pfx+7)) ;;\\n"
            f"    252) pfx=$((pfx+6)) ;;\\n"
            f"    248) pfx=$((pfx+5)) ;;\\n"
            f"    240) pfx=$((pfx+4)) ;;\\n"
            f"    224) pfx=$((pfx+3)) ;;\\n"
            f"    192) pfx=$((pfx+2)) ;;\\n"
            f"    128) pfx=$((pfx+1)) ;;\\n"
            f"  esac\\n"
            f"done\\n"
            f"unset IFS\\n"
            f'case "$reason" in\\n'
            f"  BOUND|RENEW|REBIND|REBOOT)\\n"
            f'    ip addr replace "${{new_ip_address}}/$pfx"'
            f' dev "$interface" 2>/dev/null || true\\n'
            f"    ;;\\n"
            f"  EXPIRE|FAIL|RELEASE|STOP)\\n"
            f'    ip addr del "${{old_ip_address}}/$pfx"'
            f' dev "$interface" 2>/dev/null || true\\n'
            f"    ;;\\n"
            f"esac\\n"
            f"exit 0\\n'"
            f" | tee '{config_script}' >/dev/null"
            f" && chmod 0755 '{config_script}'"
            f" && chown root:root '{config_script}'",
            sudo=True,
            shell=True,
        )
        # Run script once to catch noexec mount issues early.
        node.execute(f"'{config_script}'", sudo=True, shell=True)

    def _run_dhcp_on_iface(
        self, node: Node, interface_name: str, keep_unmanaged: bool = True
    ) -> Any:
        """Run the available DHCP client with safety guards."""
        dhcp_client = node.tools[Dhclient].command
        if dhcp_client not in ["dhclient", "dhcpcd"]:
            raise SkippedException(
                f"Passthrough NIC DHCP found unsupported client [{dhcp_client}]. "
                "Install dhclient or dhcpcd before running this test."
            )
        dhcp_pid = f"/run/dhclient-{interface_name}.pid"
        dhcp_lease = f"/var/lib/dhcp/dhclient-{interface_name}.leases"
        config_script = "/usr/local/bin/lisa-dhclient-config"

        def _wrap_aa(cmd: str) -> str:
            """Run cmd under AppArmor 'unconfined' when aa-exec is available."""
            return (
                "sh -c '"
                "if command -v aa-exec >/dev/null 2>&1; then "
                f"aa-exec -p unconfined -- {cmd}; "
                f"else {cmd}; "
                "fi'"
            )

        if dhcp_client == "dhclient":
            self._install_dhclient_scripts(node, config_script)

        # Isolate only the target interface from competing DHCP managers.
        # NM: mark this interface unmanaged instead of stopping the service.
        _nm_active = (
            node.execute(
                "systemctl is-active NetworkManager 2>/dev/null || true",
                sudo=True,
                shell=True,
            ).stdout.strip()
            == "active"
        )
        _nm_was_managed = _nm_active and (
            node.execute(
                f"nmcli -g GENERAL.NM-MANAGED device show {interface_name}"
                " 2>/dev/null || true",
                sudo=True,
                shell=True,
            )
            .stdout.strip()
            .lower()
            == "yes"
        )
        if _nm_was_managed:
            node.execute(
                f"nmcli device set {interface_name} managed no" " 2>/dev/null || true",
                sudo=True,
                shell=True,
            )
        # systemd-networkd: write a per-interface drop-in that marks it
        # unmanaged, then reload (no service stop needed).
        _nd_dropin = f"/etc/systemd/network/90-{interface_name}-unmanaged.network"
        _nd_was_managed = (
            node.execute(
                "systemctl is-active systemd-networkd 2>/dev/null || true",
                sudo=True,
                shell=True,
            ).stdout.strip()
            == "active"
        ) and (
            "unmanaged"
            not in node.execute(
                f"networkctl status {interface_name} 2>/dev/null || true",
                sudo=True,
                shell=True,
            ).stdout
        )
        if _nd_was_managed:
            node.execute(
                f"printf '[Match]\\nName={interface_name}\\n\\n"
                f"[Link]\\nUnmanaged=yes\\n' > {_nd_dropin}"
                "; networkctl reload 2>/dev/null || true",
                sudo=True,
                shell=True,
            )
        try:
            self._stop_dhcp_on_iface(node, interface_name, dhcp_client)
            node.execute(
                f"ip addr flush dev {interface_name} 2>/dev/null || true",
                sudo=True,
                shell=True,
            )
            if dhcp_client == "dhclient":
                dhcp_cmd = (
                    f"dhclient -v -1 -4 -sf {config_script}"
                    f" -pf {dhcp_pid} -lf {dhcp_lease} {interface_name}"
                )
                dhcp_cmd = _wrap_aa(dhcp_cmd)
            else:
                dhcp_cmd = f"dhcpcd -4 -1 -d {interface_name}"
            dhcp_result = node.execute(
                f"timeout -k 2s 30s {dhcp_cmd}",
                sudo=True,
                shell=True,
                timeout=45,
            )
        finally:
            if _nd_was_managed and not keep_unmanaged:
                node.execute(
                    f"rm -f {_nd_dropin}" "; networkctl reload 2>/dev/null || true",
                    sudo=True,
                    shell=True,
                )
            if _nm_was_managed and not keep_unmanaged:
                node.execute(
                    f"nmcli device set {interface_name} managed yes"
                    " 2>/dev/null || true",
                    sudo=True,
                    shell=True,
                )
        return dhcp_result

    def _raise_dhcp_failure(
        self,
        node: Node,
        interface_name: str,
        dhcp_result: Any,
        host_node: Optional[RemoteNode] = None,
        host_nic_name: str = "",
    ) -> None:
        """Gather diagnostics and raise LisaException for a DHCP failure."""
        fail_link = node.execute(
            f"ip -d link show {interface_name}", sudo=True, shell=True
        ).stdout
        fail_addr = node.execute(
            f"ip -4 addr show {interface_name}", sudo=True, shell=True
        ).stdout
        fail_routes = node.execute("ip -4 route", sudo=True, shell=True).stdout
        fail_rp = node.execute(
            f"sysctl net.ipv4.conf.{interface_name}.rp_filter"
            " net.ipv4.conf.all.rp_filter 2>/dev/null || true",
            sudo=True,
            shell=True,
        ).stdout
        fail_host_info = ""
        if host_node is not None:
            _iface_arg = host_nic_name or ""
            _rp_iface = (
                f" net.ipv4.conf.{host_nic_name}.rp_filter" if host_nic_name else ""
            )
            _h = host_node.execute(
                f"echo '--- HOST ip link ---';"
                f" ip -d link show {_iface_arg} 2>/dev/null || ip -d link show;"
                f" echo '--- HOST ip route default ---';"
                f" ip -4 route show default;"
                f" echo '--- HOST rp_filter ---';"
                f" sysctl net.ipv4.conf.all.rp_filter{_rp_iface} 2>/dev/null || true",
                sudo=True,
                shell=True,
            ).stdout
            fail_host_info = f"--- HOST diagnostics ---\n{_h}\n"
        raise LisaException(
            f"DHCP lease failed on interface {interface_name} "
            f"(dhclient exit code {dhcp_result.exit_code}).\n"
            f"dhclient output:\n{dhcp_result.stdout}\n"
            f"--- ip -d link show ---\n{fail_link}\n"
            f"--- ip -4 addr show ---\n{fail_addr}\n"
            f"--- ip -4 route ---\n{fail_routes}\n"
            f"--- rp_filter ---\n{fail_rp}\n"
            f"{fail_host_info}"
        )

    def _get_host_as_server(self, variables: Dict[str, Any]) -> RemoteNode:
        ip = variables.get("baremetal_host_ip", "")
        username = variables.get("baremetal_host_username", "")
        passwd = variables.get("baremetal_host_password", "")
        private_key = variables.get("baremetal_host_private_key_file", "")

        if not (ip and username and (passwd or private_key)):
            raise SkippedException(
                "Server-Node details are not provided. Required: "
                "baremetal_host_ip, baremetal_host_username, and either "
                "baremetal_host_password or baremetal_host_private_key_file"
            )

        server = RemoteNode(
            runbook=schema.Node(name="baremetal-host"),
            index=-1,
            logger_name="baremetal-host",
            parent_logger=get_logger("baremetal-host-platform"),
        )
        server.set_connection_info(
            address=ip,
            public_address=ip,
            public_port=22,
            username=username,
            password=passwd,
            private_key_file=private_key,
        )
        server.internal_address = ip

        server.initialize()

        # Track baremetal host for cleanup.
        if server not in self._baremetal_hosts:
            self._baremetal_hosts.append(server)
        return server

    def _get_passthrough_peer(self, variables: Dict[str, Any]) -> RemoteNode:
        ip = variables.get("passthrough_peer_ip", "")
        username = variables.get("passthrough_peer_username", "")
        password = variables.get("passthrough_peer_password", "")
        private_key = variables.get("passthrough_peer_private_key_file", "")
        if not (ip and username and (password or private_key)):
            raise SkippedException(
                "Independent passthrough peer details are not provided. Required: "
                "passthrough_peer_ip, passthrough_peer_username, and either "
                "passthrough_peer_password or passthrough_peer_private_key_file. "
                "The peer IP must be assigned to the remote peer's dedicated "
                "physical PCI test NIC."
            )

        peer = RemoteNode(
            runbook=schema.Node(name="passthrough-peer"),
            index=-1,
            logger_name="passthrough-peer",
            parent_logger=get_logger("passthrough-peer-platform"),
        )
        peer.set_connection_info(
            address=ip,
            public_address=ip,
            public_port=22,
            username=username,
            password=password,
            private_key_file=private_key,
        )
        peer.internal_address = ip
        peer.initialize()
        if isinstance(peer.os, Windows):
            peer.close()
            peer.cleanup()
            raise SkippedException(
                "Measured passthrough baselines currently require a Linux remote "
                "peer so the same iperf and NTTTCP profiles run in both phases."
            )
        if peer not in self._baremetal_hosts:
            self._baremetal_hosts.append(peer)
        return peer

    def _skip_if_windows_server(self, server: RemoteNode, tool_name: str) -> None:
        if isinstance(server.os, Windows):
            if server in self._baremetal_hosts:
                server.close()
                server.cleanup()
                self._baremetal_hosts.remove(server)
            raise SkippedException(
                f"Host/guest passthrough performance with {tool_name} requires "
                "Linux server tooling. Use the NTTTCP passthrough cases for "
                "Windows baremetal hosts."
            )

    def _perf_ntttcp_with_windows_server(
        self,
        test_result: TestResult,
        client: RemoteNode,
        server: RemoteNode,
        client_nic_name: str,
        udp_mode: bool,
        test_case_name: str,
    ) -> Tuple[List[NetworkThroughputMessage], str]:
        client_ntttcp = client.tools[Ntttcp]
        server_ntttcp = server.tools[Ntttcp]
        client_ntttcp.setup_system(udp_mode)
        server_ntttcp.setup_system(udp_mode, set_task_max=False)
        ntttcp_messages: List[NetworkThroughputMessage] = []
        server_nic_name = ""

        try:
            client_ip = client.tools[Ip]
            self._refresh_passthrough_nic_address(client, client_nic_name)
            client_mtu = client_ip.get_mtu(client_nic_name)
            server_nic_name = self._get_windows_route_interface_name(
                server, client.internal_address
            )
            if udp_mode:
                connections = NTTTCP_UDP_CONCURRENCY
                max_server_threads = WINDOWS_NTTTCP_MAX_SERVER_THREADS
            else:
                connections = [
                    connection
                    for connection in NTTTCP_TCP_CONCURRENCY
                    if connection <= WINDOWS_NTTTCP_MAX_MIXED_TCP_CONNECTIONS
                ]
                max_server_threads = WINDOWS_NTTTCP_MAX_MIXED_TCP_CONNECTIONS

            for test_thread in connections:
                self._refresh_passthrough_nic_address(client, client_nic_name)
                server_data_path_ip = self._get_windows_route_source_ip(
                    server, client.internal_address
                )
                client.execute(
                    f"ip route replace {server_data_path_ip}/32 "
                    f"dev {client_nic_name} src {client.internal_address}",
                    sudo=True,
                    shell=True,
                    expected_exit_code=0,
                )
                if test_thread < max_server_threads:
                    num_threads_p = test_thread
                    num_threads_n = 1
                else:
                    num_threads_p = max_server_threads
                    num_threads_n = int(test_thread / num_threads_p)
                # UDP uses a 1 KB buffer; TCP uses 64 KB, except for single-stream
                # which uses 1 MB to maximize per-connection throughput.
                buffer_size = 1 if udp_mode else 64  # KB
                if not udp_mode and num_threads_p == 1 and num_threads_n == 1:
                    buffer_size = 1024  # 1 MB for single-stream TCP
                use_no_sync = True

                receiver_process = (
                    client_ntttcp.run_as_server_async(
                        client_nic_name,
                        ports_count=num_threads_p,
                        buffer_size=buffer_size,
                        udp_mode=True,
                        dev_differentiator="",
                        no_sync=use_no_sync,
                    )
                    if udp_mode
                    else server_ntttcp.run_as_server_async(
                        "",
                        ports_count=num_threads_p,
                        buffer_size=buffer_size,
                        server_ip=server_data_path_ip,
                        dev_differentiator="",
                        no_sync=use_no_sync,
                    )
                )
                try:
                    if udp_mode:
                        sender_result = server_ntttcp.run_as_client(
                            "",
                            client.internal_address,
                            threads_count=num_threads_n,
                            ports_count=num_threads_p,
                            buffer_size=buffer_size,
                            udp_mode=True,
                            no_sync=use_no_sync,
                        )
                    else:
                        sender_result = client_ntttcp.run_as_client(
                            client_nic_name,
                            server_data_path_ip,
                            threads_count=num_threads_n,
                            ports_count=num_threads_p,
                            buffer_size=buffer_size,
                            dev_differentiator="",
                            no_sync=use_no_sync,
                            source_ip=client.internal_address,
                        )
                    receiver_result = receiver_process.wait_result(
                        timeout=WINDOWS_NTTTCP_RECEIVER_WAIT_TIMEOUT
                    )
                finally:
                    server.tools[PowerShell].run_cmdlet(
                        "Stop-Process -Name ntttcp -Force"
                        " -ErrorAction SilentlyContinue",
                        force_run=True,
                        fail_on_error=False,
                        timeout=30,
                    )

                parsed_client_result = (
                    server_ntttcp.create_ntttcp_result(sender_result, role="client")
                    if udp_mode
                    else client_ntttcp.create_ntttcp_result(
                        sender_result, role="client"
                    )
                )
                try:
                    parsed_server_result = (
                        client_ntttcp.create_ntttcp_result(receiver_result)
                        if udp_mode
                        else server_ntttcp.create_ntttcp_result(receiver_result)
                    )
                except (AssertionError, LisaException) as parse_error:
                    receiver_node = "Linux guest" if udp_mode else "Windows host"
                    raise LisaException(
                        f"Failed to parse NTTTCP receiver output from {receiver_node} "
                        f"for {test_case_name} with {test_thread} connections. "
                        "Verify that the receiver completed and emitted NTTTCP "
                        "totals before publishing performance data. "
                        f"Exit code: {receiver_result.exit_code}. "
                        f"Stdout: {receiver_result.stdout[:2000]}. "
                        f"Stderr: {receiver_result.stderr[:2000]}"
                    ) from parse_error
                if udp_mode:
                    ntttcp_message: NetworkThroughputMessage = (
                        client_ntttcp.create_ntttcp_udp_performance_message(
                            parsed_server_result,
                            parsed_client_result,
                            str(test_thread),
                            buffer_size,
                            test_case_name,
                            test_result,
                            client_mtu,
                        )
                    )
                else:
                    ntttcp_message = (
                        client_ntttcp.create_ntttcp_tcp_performance_message(
                            parsed_server_result,
                            parsed_client_result,
                            Decimal(0),
                            str(test_thread),
                            buffer_size,
                            test_case_name,
                            test_result,
                            client_mtu,
                        )
                    )
                notifier.notify(ntttcp_message)
                ntttcp_messages.append(ntttcp_message)
        finally:
            client_ntttcp.restore_system(udp_mode)
            server_ntttcp.restore_system(udp_mode)
        return ntttcp_messages, server_nic_name

    def _get_windows_route_source_ip(self, server: RemoteNode, remote_ip: str) -> str:
        escaped_remote_ip = remote_ip.replace("'", "''")
        source_ip = cast(
            str,
            server.tools[PowerShell].run_cmdlet(
                "$route = Find-NetRoute -RemoteIPAddress "
                f"'{escaped_remote_ip}' -ErrorAction Stop | Select-Object -First 1; "
                "$sourceAddress = $null; "
                "if ($route) { "
                "  $sourceProperty = $route.PSObject.Properties['IPAddress']; "
                "  if ($sourceProperty) { $sourceAddress = $sourceProperty.Value; } "
                "  if (-not $sourceAddress -and $route.InterfaceIndex) { "
                "    $sourceAddress = Get-NetIPAddress -AddressFamily IPv4 "
                "      -InterfaceIndex $route.InterfaceIndex -ErrorAction Stop | "
                "      Where-Object { $_.AddressState -eq 'Preferred' "
                "        -and -not $_.SkipAsSource "
                "        -and $_.IPAddress -ne '127.0.0.1' "
                "        -and $_.IPAddress -notlike '169.254.*' } | "
                "      Select-Object -First 1 -ExpandProperty IPAddress; "
                "  } "
                "} "
                "if ($sourceAddress) { $sourceAddress.ToString() }",
                fail_on_error=False,
                force_run=True,
            ),
        ).strip()
        if not source_ip:
            raise LisaException(
                f"Failed to resolve the Windows source IP for route to {remote_ip}. "
                "Verify the Windows host has an IPv4 address and route on the "
                "passthrough data-path NIC."
            )
        return source_ip

    def _get_windows_route_interface_name(
        self, server: RemoteNode, remote_ip: str
    ) -> str:
        escaped_remote_ip = remote_ip.replace("'", "''")
        interface_name = cast(
            str,
            server.tools[PowerShell].run_cmdlet(
                "$route = Find-NetRoute -RemoteIPAddress "
                f"'{escaped_remote_ip}' -ErrorAction Stop | Select-Object -First 1; "
                "if ($route) { "
                "  $adapter = Get-NetAdapter -InterfaceIndex $route.InterfaceIndex "
                "    -ErrorAction Stop; "
                "  if ($adapter) { $adapter.Name.ToString() } "
                "}",
                fail_on_error=False,
                force_run=True,
            ),
        ).strip()
        if not interface_name:
            raise SkippedException(
                f"Cannot determine the Windows adapter for route to {remote_ip}. "
                "Verify the Windows host has a route on the passthrough data-path NIC."
            )
        return interface_name

    def _get_host_nic_name(self, node: RemoteNode) -> str:
        ip = (
            node.internal_address
            or node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS]
        )
        addresses = node.execute(
            cmd="ip -4 -o addr show",
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Cannot list Linux interfaces while resolving data-plane IP [{ip}]."
            ),
        ).stdout
        regex_pattern = re.compile(
            rf"^\d+:\s+(?P<interface>[^@\s]+)(?:@\S+)?\s+" rf"inet\s+{re.escape(ip)}/"
        )
        interface = find_group_in_lines(
            lines=addresses,
            pattern=regex_pattern,
            single_line=True,
        ).get("interface", "")
        if not interface:
            raise LisaException(
                f"Cannot find a Linux interface with data-plane IP [{ip}] on "
                f"node [{node.name}]. Configure passthrough_peer_ip with an address "
                f"assigned to the peer's physical PCI test NIC. Interfaces: "
                f"[{addresses[:1000]}]"
            )
        return interface

    def _validate_physical_pci_nic(
        self,
        node: Node,
        interface_name: str,
        endpoint_role: str,
    ) -> None:
        nic_details_output = node.execute(
            cmd=(
                f"device_path=$(readlink -f /sys/class/net/{interface_name}/device "
                "2>/dev/null); "
                "subsystem=; bdf=; pci_class=; driver=; is_vf=false; "
                "sriov_totalvfs=unavailable; sriov_numvfs=unavailable; "
                'if [ -n "$device_path" ]; then '
                'subsystem_path=$(readlink -f "$device_path/subsystem" '
                "2>/dev/null); subsystem=${subsystem_path##*/}; "
                "bdf=${device_path##*/}; "
                'pci_class=$(cat "$device_path/class" 2>/dev/null); '
                'driver_path=$(readlink -f "$device_path/driver" '
                "2>/dev/null); driver=${driver_path##*/}; "
                'if [ -e "$device_path/physfn" ]; then is_vf=true; fi; '
                'if [ -r "$device_path/sriov_totalvfs" ]; then '
                'sriov_totalvfs=$(cat "$device_path/sriov_totalvfs"); fi; '
                'if [ -r "$device_path/sriov_numvfs" ]; then '
                'sriov_numvfs=$(cat "$device_path/sriov_numvfs"); fi; fi; '
                "printf '%s\\n' \"device_path=$device_path\" "
                '"subsystem=$subsystem" "bdf=$bdf" '
                '"pci_class=$pci_class" "driver=$driver" '
                '"is_vf=$is_vf" "sriov_totalvfs=$sriov_totalvfs" '
                '"sriov_numvfs=$sriov_numvfs"'
            ),
            sudo=True,
            shell=True,
            no_info_log=True,
            no_error_log=True,
        ).stdout.strip()
        nic_details = dict(
            line.split("=", maxsplit=1)
            for line in nic_details_output.splitlines()
            if "=" in line
        )
        device_path = nic_details.get("device_path", "")
        subsystem = nic_details.get("subsystem", "")
        bdf = nic_details.get("bdf", "")
        pci_class = nic_details.get("pci_class", "")
        driver = nic_details.get("driver", "") or "unavailable"
        is_vf = nic_details.get("is_vf", "false") == "true"
        sriov_totalvfs = nic_details.get("sriov_totalvfs", "unavailable")
        sriov_numvfs = nic_details.get("sriov_numvfs", "unavailable")

        node.log.info(
            f"{endpoint_role.capitalize()} data NIC "
            f"[{node.name}:{interface_name}] PCI identity: BDF "
            f"[{bdf or 'unavailable'}], class [{pci_class or 'unavailable'}], "
            f"driver [{driver}], VF [{is_vf}]"
        )
        node.log.info(
            f"{endpoint_role.capitalize()} data NIC "
            f"[{node.name}:{interface_name}] SR-IOV state: sriov_totalvfs "
            f"[{sriov_totalvfs}], sriov_numvfs [{sriov_numvfs}]"
        )

        is_pci_network_function = (
            subsystem == "pci"
            and re.fullmatch(
                r"[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]", bdf
            )
            is not None
            and pci_class.lower().startswith("0x02")
        )
        if not is_pci_network_function:
            raise SkippedException(
                f"The {endpoint_role} data NIC [{node.name}:{interface_name}] is "
                "not a physical PCI network function. Configure the data-plane IP "
                "on a dedicated physical PCI NIC before running this test. "
                f"Resolved device path [{device_path or 'unavailable'}], subsystem "
                f"[{subsystem or 'unavailable'}], class "
                f"[{pci_class or 'unavailable'}]."
            )
        if is_vf:
            raise SkippedException(
                f"The {endpoint_role} data NIC [{node.name}:{interface_name}] at "
                f"BDF [{bdf}] is an SR-IOV virtual function, not a physical "
                "function. Configure the data-plane IP on a dedicated physical "
                "PCI NIC before running this test."
            )

    def _get_cleanup_nodes(self, environment: Environment) -> List[Node]:
        all_nodes = list(environment.nodes.list())
        if (
            environment.platform
            and environment.platform.type_name() == CLOUD_HYPERVISOR
        ):
            platform_host = getattr(environment.platform, "host_node", None)
            if isinstance(platform_host, Node) and platform_host not in all_nodes:
                all_nodes.append(platform_host)
        if self._baremetal_hosts:
            all_nodes.extend(self._baremetal_hosts)
        return all_nodes

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        all_nodes = self._get_cleanup_nodes(environment)

        def do_process_cleanup(process: str, node: Node) -> None:
            try:
                if isinstance(node.os, Windows):
                    escaped_process = process.replace("'", "''")
                    node.tools[PowerShell].run_cmdlet(
                        cmdlet=(
                            f"$p = Get-Process -Name '{escaped_process}' "
                            "-ErrorAction SilentlyContinue; "
                            "if ($p) { $p | Stop-Process -Force "
                            "-ErrorAction SilentlyContinue }"
                        ),
                        fail_on_error=False,
                    )
                    return

                kill = node.tools[Kill]
                kill.by_name(process, ignore_not_exist=True)
            except LisaException as identifier_error:
                log.debug(
                    f"Skipping Kill tool-based cleanup for '{process}' on "
                    f"node '{node.name}': {identifier_error}"
                )
                if isinstance(node.os, Windows):
                    return

                node.execute(
                    cmd=(
                        f"pids=$(pidof {process} 2>/dev/null || true); "
                        '[ -z "$pids" ] || kill -9 $pids || true'
                    ),
                    shell=True,
                    sudo=True,
                )

        def do_sysctl_cleanup(node: Node) -> None:
            if isinstance(node.os, Windows):
                return

            try:
                node.tools[Sysctl].reset()
            except LisaException as sysctl_error:
                log.debug(
                    f"Skipping sysctl cleanup on node '{node.name}': {sysctl_error}"
                )

        cleanup_tasks: List[Callable[[], None]] = []
        for process in ["lagscope", "netperf", "netserver", "ntttcp", "iperf3"]:
            for node in all_nodes:
                cleanup_tasks.append(partial(do_process_cleanup, process, node))

        run_in_parallel(cleanup_tasks)
        run_in_parallel([partial(do_sysctl_cleanup, x) for x in all_nodes])

        for external_host in self._baremetal_hosts:
            external_host.close()
            external_host.cleanup()
        self._baremetal_hosts.clear()
