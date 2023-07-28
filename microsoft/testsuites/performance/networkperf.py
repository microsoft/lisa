# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any

from lisa import (
    Logger,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    node_requirement,
    schema,
    search_space,
    simple_requirement,
)
from lisa.environment import Environment
from lisa.features import Sriov, Synthetic
from lisa.testsuite import TestResult
from lisa.tools.iperf3 import (
    IPERF_TCP_BUFFER_LENGTHS,
    IPERF_TCP_CONCURRENCY,
    IPERF_UDP_BUFFER_LENGTHS,
    IPERF_UDP_CONCURRENCY,
)
from lisa.tools.sockperf import SOCKPERF_TCP, SOCKPERF_UDP
from microsoft.testsuites.performance.common import (
    cleanup_process,
    perf_iperf,
    perf_ntttcp,
    perf_sockperf,
    perf_tcp_latency,
    perf_tcp_pps,
)


@TestSuiteMetadata(
    area="network",
    category="performance",
    description="""
    This test suite is to validate linux network performance.
    """,
)
class NetworkPerformace(TestSuite):
    TIMEOUT = 12000
    PPS_TIMEOUT = 3000

    @TestCaseMetadata(
        description="""
        This test case uses lagscope to test synthetic network latency.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_tcp_latency_synthetic(self, result: TestResult) -> None:
        perf_tcp_latency(result)

    @TestCaseMetadata(
        description="""
        This test case uses lagscope to test sriov network latency.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_tcp_latency_sriov(self, result: TestResult) -> None:
        perf_tcp_latency(result)

    @TestCaseMetadata(
        description="""
        This test case uses sar to test synthetic network PPS (Packets Per Second)
         when running netperf with single port.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_tcp_single_pps_synthetic(self, result: TestResult) -> None:
        perf_tcp_pps(result, "singlepps")

    @TestCaseMetadata(
        description="""
        This test case uses sar to test sriov network PPS (Packets Per Second)
         when running netperf with single port.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_tcp_single_pps_sriov(self, result: TestResult) -> None:
        perf_tcp_pps(result, "singlepps")

    @TestCaseMetadata(
        description="""
        This test case uses sar to test synthetic network PPS (Packets Per Second)
         when running netperf with multiple ports.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_tcp_max_pps_synthetic(self, result: TestResult) -> None:
        perf_tcp_pps(result, "maxpps")

    @TestCaseMetadata(
        description="""
        This test case uses sar to test sriov network PPS (Packets Per Second)
         when running netperf with multiple ports.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_tcp_max_pps_sriov(self, result: TestResult) -> None:
        perf_tcp_pps(result, "maxpps")

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test synthetic tcp network throughput for
         128 connections.
        """,
        priority=2,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_tcp_ntttcp_128_connections_synthetic(self, result: TestResult) -> None:
        perf_ntttcp(result, connections=[128])

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test synthetic tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=2,
                memory_mb=search_space.IntRange(min=8192),
                network_interface=Synthetic(),
            )
        ),
    )
    def perf_tcp_ntttcp_synthetic(self, result: TestResult) -> None:
        perf_ntttcp(result)

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test sriov tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=2,
                memory_mb=search_space.IntRange(min=8192),
                network_interface=Sriov(),
            )
        ),
    )
    def perf_tcp_ntttcp_sriov(self, result: TestResult) -> None:
        perf_ntttcp(result)

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test synthetic udp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_udp_1k_ntttcp_synthetic(self, result: TestResult) -> None:
        perf_ntttcp(result, udp_mode=True)

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test sriov udp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_udp_1k_ntttcp_sriov(self, result: TestResult) -> None:
        perf_ntttcp(result, udp_mode=True)

    @TestCaseMetadata(
        description="""
        This test case uses iperf3 to test synthetic tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_tcp_iperf_synthetic(self, result: TestResult) -> None:
        perf_iperf(
            result,
            connections=IPERF_TCP_CONCURRENCY,
            buffer_length_list=IPERF_TCP_BUFFER_LENGTHS,
        )

    @TestCaseMetadata(
        description="""
        This test case uses iperf3 to test sriov tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_tcp_iperf_sriov(self, result: TestResult) -> None:
        perf_iperf(
            result,
            connections=IPERF_TCP_CONCURRENCY,
            buffer_length_list=IPERF_TCP_BUFFER_LENGTHS,
        )

    @TestCaseMetadata(
        description="""
        This test case uses iperf to test synthetic udp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_udp_iperf_synthetic(self, result: TestResult) -> None:
        perf_iperf(
            result,
            connections=IPERF_UDP_CONCURRENCY,
            buffer_length_list=IPERF_UDP_BUFFER_LENGTHS,
            udp_mode=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses iperf to test sriov udp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_udp_iperf_sriov(self, result: TestResult) -> None:
        perf_iperf(
            result,
            connections=IPERF_UDP_CONCURRENCY,
            buffer_length_list=IPERF_UDP_BUFFER_LENGTHS,
            udp_mode=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses sockperf to test sriov network latency.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_sockperf_latency_tcp_sriov(self, result: TestResult) -> None:
        perf_sockperf(result, SOCKPERF_TCP, "perf_sockperf_latency_tcp_sriov")

    @TestCaseMetadata(
        description="""
        This test case uses sockperf to test sriov network latency.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_sockperf_latency_udp_sriov(self, result: TestResult) -> None:
        perf_sockperf(result, SOCKPERF_UDP, "perf_sockperf_latency_udp_sriov")

    @TestCaseMetadata(
        description="""
        This test case uses sockperf to test synthetic network latency.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_sockperf_latency_udp_synthetic(self, result: TestResult) -> None:
        perf_sockperf(result, SOCKPERF_UDP, "perf_sockperf_latency_udp_synthetic")

    @TestCaseMetadata(
        description="""
        This test case uses sockperf to test synthetic network latency.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_sockperf_latency_tcp_synthetic(self, result: TestResult) -> None:
        perf_sockperf(result, SOCKPERF_TCP, "perf_sockperf_latency_tcp_synthetic")

    @TestCaseMetadata(
        description="""
        This test case uses sockperf to test sriov network latency.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_sockperf_latency_tcp_sriov_busy_poll(self, result: TestResult) -> None:
        perf_sockperf(
            result,
            SOCKPERF_TCP,
            "perf_sockperf_latency_tcp_sriov_busy_poll",
            set_busy_poll=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses sockperf to test sriov network latency.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_sockperf_latency_udp_sriov_busy_poll(self, result: TestResult) -> None:
        perf_sockperf(
            result,
            SOCKPERF_UDP,
            "perf_sockperf_latency_udp_sriov_busy_poll",
            set_busy_poll=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses sockperf to test synthetic network latency.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_sockperf_latency_udp_synthetic_busy_poll(self, result: TestResult) -> None:
        perf_sockperf(
            result,
            SOCKPERF_UDP,
            "perf_sockperf_latency_udp_synthetic_busy_poll",
            set_busy_poll=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses sockperf to test synthetic network latency.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_sockperf_latency_tcp_synthetic_busy_poll(self, result: TestResult) -> None:
        perf_sockperf(
            result,
            SOCKPERF_TCP,
            "perf_sockperf_latency_tcp_synthetic_busy_poll",
            set_busy_poll=True,
        )

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        for process in ["lagscope", "netperf", "netserver", "ntttcp", "iperf3"]:
            cleanup_process(environment, process)
