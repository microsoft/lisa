# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from functools import partial
from typing import Any, Dict, List, Tuple

from assertpy import assert_that

from microsoft.testsuites.performance.common import (
    cleanup_process,
    perf_iperf,
    perf_ntttcp,
    perf_sockperf,
    perf_tcp_latency,
    perf_tcp_pps,
)

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
from lisa.environment import Environment, Node
from lisa.features import Sriov, Synthetic
from lisa.operating_system import BSD, Windows
from lisa.testsuite import TestResult
from lisa.tools import Ethtool, Sysctl
from lisa.tools.iperf3 import (
    IPERF_TCP_BUFFER_LENGTHS,
    IPERF_TCP_CONCURRENCY,
    IPERF_UDP_BUFFER_LENGTHS,
    IPERF_UDP_CONCURRENCY,
)
from lisa.tools.sockperf import SOCKPERF_TCP, SOCKPERF_UDP
from lisa.util import SkippedException, UnsupportedOperationException
from lisa.util.parallel import run_in_parallel


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
    def perf_tcp_ntttcp_128_connections_synthetic(
        self, result: TestResult, variables: Dict[str, Any]
    ) -> None:
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
    def perf_tcp_ntttcp_synthetic(
        self, result: TestResult, variables: Dict[str, Any]
    ) -> None:
        perf_ntttcp(result, variables=variables)

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
    def perf_tcp_ntttcp_sriov(
        self, result: TestResult, variables: Dict[str, Any]
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from test result"

        # The mlx5 driver exposes a private flag that controls RX CQE
        # coalescing. Enable it on the SRIOV VF interface of every node before
        # running the throughput test, and revert to the original value after.
        priv_flag = "rx_cqe_coalesce_4"
        reverts: List[Tuple[Node, str, bool]] = []
        try:
            for node in environment.nodes.list():
                # Print the loaded mana driver modules for diagnostics.
                mana_modules = node.execute(
                    "lsmod | grep mana", sudo=True, shell=True
                ).stdout
                node.log.info(f"mana modules on node {node.name}:\n{mana_modules}")

                ethtool = node.tools[Ethtool]
                for interface in node.nics.get_pci_nics(exclude_ib=True):
                    # Step 1: show the current private flags.
                    try:
                        original_flags = ethtool.get_device_priv_flags(interface)
                    except UnsupportedOperationException as e:
                        raise SkippedException(e)

                    if priv_flag not in original_flags.flags:
                        raise SkippedException(
                            f"Private flag '{priv_flag}' is not available on interface "
                            f"{interface} of node {node.name}. The driver may not "
                            "support it. Skipping test."
                        )

                    original_value = original_flags.flags[priv_flag]
                    # Changing a NIC private flag alters device state.
                    node.mark_dirty()

                    # Step 2: enable the private flag and Step 3: re-read to
                    # confirm the change took effect.
                    try:
                        updated_flags = ethtool.set_device_priv_flag(
                            interface, priv_flag, True
                        )
                    except UnsupportedOperationException as e:
                        raise SkippedException(e)
                    reverts.append((node, interface, original_value))
                    assert_that(updated_flags.flags[priv_flag]).described_as(
                        f"Enabling private flag '{priv_flag}' on interface "
                        f"{interface} of node {node.name} did not take effect"
                    ).is_true()

            perf_ntttcp(result, variables=variables)
        finally:
            # Revert each private flag we changed back to its original value.
            for node, interface, original_value in reverts:
                node.tools[Ethtool].set_device_priv_flag(
                    interface, priv_flag, original_value
                )

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test synthetic udp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_udp_1k_ntttcp_synthetic(
        self, result: TestResult, variables: Dict[str, Any]
    ) -> None:
        perf_ntttcp(result, udp_mode=True, variables=variables)

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test sriov udp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_udp_1k_ntttcp_sriov(
        self, result: TestResult, variables: Dict[str, Any]
    ) -> None:
        perf_ntttcp(result, udp_mode=True, variables=variables)

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

    # Marked all following tests to skip on BSD since
    # sockperf compilation is not natively supported at this time
    # This is due to the default compiler on freebsd being c++17
    # and sockperf is designed to compile on c+11 which is no longer available
    # This is a way to compile it but it requires adding a patch file
    # to the sockperf repo to remove references to std::unary and std::binary
    @TestCaseMetadata(
        description="""
        This test case uses sockperf to test sriov network latency.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
            unsupported_os=[BSD, Windows],
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
            unsupported_os=[BSD, Windows],
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
            unsupported_os=[BSD, Windows],
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
            unsupported_os=[BSD, Windows],
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
            unsupported_os=[BSD, Windows],
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
            unsupported_os=[BSD, Windows],
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
            unsupported_os=[BSD, Windows],
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
            unsupported_os=[BSD, Windows],
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

        # use these cleanup functions
        def do_process_cleanup(process: str) -> None:
            cleanup_process(environment, process)

        def do_sysctl_cleanup(node: Node) -> None:
            node.tools[Sysctl].reset()

        # to run parallel cleanup of processes and sysctl settings
        run_in_parallel(
            [
                partial(do_process_cleanup, x)
                for x in [
                    "lagscope",
                    "netperf",
                    "netserver",
                    "ntttcp",
                    "iperf3",
                ]
            ]
        )
        run_in_parallel(
            [partial(do_sysctl_cleanup, x) for x in environment.nodes.list()]
        )
