# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
#
# TRex-based network performance test cases.
#
# These tests require at least 2 nodes (sender + receiver) with SR-IOV NICs
# so that TRex/DPDK can drive traffic at line rate without the overhead of
# the paravirtual network stack.
#
# How to run manually
# -------------------
# 1. Provision two VMs with SR-IOV-capable NICs (e.g. Standard_D8s_v5 on Azure).
# 2. Run LISA selecting this test suite::
#
#       python lisa.py run                          \
#           --runbook microsoft/runbook/azure.yml   \
#           --select_test "perf_tcp_stateless_trex_sriov|perf_udp_stateless_trex_sriov"
#
# 3. Results are emitted as LISA UnifiedPerfMessage objects and can be consumed
#    by any configured notifier (e.g. Azure Data Explorer, console).

from typing import List

from lisa import (
    Logger,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.environment import Environment
from lisa.features import Sriov
from lisa.operating_system import BSD, Windows
from lisa.testsuite import TestResult
from lisa.tools import Trex
from lisa.util import LisaException


# Packet sizes to exercise for UDP tests (bytes, excluding FCS)
_UDP_PACKET_SIZES: List[int] = [64, 512, 1500]

# Default traffic duration (seconds)
_TRAFFIC_DURATION = 30

# Default TX rate (Gbps) – kept conservative so the test passes on most SKUs
_DEFAULT_RATE_GBPS = 1.0

# Suite-level timeout (seconds): allow for install + multiple runs
_TIMEOUT = 3600


@TestSuiteMetadata(
    area="network",
    category="performance",
    description="""
    TRex-based DPDK network performance tests.

    TRex (https://trex-tgn.cisco.com) is a Cisco open-source, high-performance
    traffic generator built on top of DPDK.  It can generate millions of flows
    at line rate and provides accurate per-flow statistics.

    These tests validate SR-IOV NIC performance at the DPDK layer, filling a
    gap in LISA's existing iperf3/ntttcp/netperf coverage which relies on the
    kernel networking stack.
    """,
)
class NetworkPerformanceTrex(TestSuite):

    @TestCaseMetadata(
        description="""
        Stateless TCP throughput test using TRex on SR-IOV NICs.

        The sender node runs the TRex traffic generator in stateless mode and
        injects TCP frames at the configured rate.  The receiver node acts as a
        passive traffic sink.  TX and RX throughput (Gbps) and packet-per-second
        rates are collected and emitted as LISA performance messages.
        """,
        priority=3,
        timeout=_TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_tcp_stateless_trex_sriov(
        self, result: TestResult, log: Logger, environment: Environment
    ) -> None:
        _run_trex_stateless(
            result=result,
            log=log,
            environment=environment,
            protocol="TCP",
            packet_sizes=[1024],
            duration=_TRAFFIC_DURATION,
            rate_gbps=_DEFAULT_RATE_GBPS,
        )

    @TestCaseMetadata(
        description="""
        Stateless UDP throughput test using TRex on SR-IOV NICs.

        Same as the TCP variant above but uses UDP frames at three different
        packet sizes (64 B, 512 B, 1500 B) to characterise NIC forwarding
        performance across different MTU scenarios.
        """,
        priority=3,
        timeout=_TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_udp_stateless_trex_sriov(
        self, result: TestResult, log: Logger, environment: Environment
    ) -> None:
        _run_trex_stateless(
            result=result,
            log=log,
            environment=environment,
            protocol="UDP",
            packet_sizes=_UDP_PACKET_SIZES,
            duration=_TRAFFIC_DURATION,
            rate_gbps=_DEFAULT_RATE_GBPS,
        )


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _run_trex_stateless(
    result: TestResult,
    log: Logger,
    environment: Environment,
    protocol: str,
    packet_sizes: List[int],
    duration: int,
    rate_gbps: float,
) -> None:
    """
    Core logic shared by both TCP and UDP TRex test cases.

    Architecture
    ------------
    * ``sender`` (nodes[0]) – TRex server + traffic generator
    * ``receiver`` (nodes[1]) – passive traffic sink

    Steps
    -----
    1. Resolve the receiver's IP address (first NIC).
    2. Install TRex on the sender (downloads tarball, sets up hugepages).
    3. Start the TRex server daemon on the sender.
    4. For each requested packet size, run a stateless traffic profile and
       collect statistics.
    5. Emit LISA UnifiedPerfMessage objects for each metric.
    6. Stop the TRex server and release hugepages.
    """
    nodes = environment.nodes
    sender = nodes[0]
    receiver = nodes[1]

    # ------------------------------------------------------------------
    # 1. Resolve receiver IP using the node's internal address
    # ------------------------------------------------------------------
    receiver_ip = receiver.internal_address
    if not receiver_ip:
        raise LisaException(
            "Could not determine receiver IP address for TRex traffic target"
        )
    log.debug(f"TRex receiver IP: {receiver_ip}")

    # ------------------------------------------------------------------
    # 2. Install TRex on sender (idempotent – cached after first call)
    # ------------------------------------------------------------------
    trex = sender.tools[Trex]

    # ------------------------------------------------------------------
    # 3. Start TRex server
    # ------------------------------------------------------------------
    trex.start_server()

    try:
        for pkt_size in packet_sizes:
            log.info(
                f"Running TRex {protocol} stateless traffic: "
                f"packet_size={pkt_size}B  rate={rate_gbps}Gbps  "
                f"duration={duration}s"
            )

            # ---- Run traffic ----
            trex_result = trex.run_stateless_traffic(
                server_ip=receiver_ip,
                duration=duration,
                packet_size=pkt_size,
                rate_gbps=rate_gbps,
                protocol=protocol,
            )

            test_case_name = result.runtime_data.metadata.name

            # ---- Emit structured performance messages ----
            trex.send_trex_unified_perf_messages(
                node=sender,
                test_result=result,
                test_case_name=test_case_name,
                trex_result=trex_result,
            )

            # ---- Also emit the legacy typed messages for back-compat ----
            if protocol.upper() == "TCP":
                trex.create_tcp_performance_message(
                    trex_result=trex_result,
                    test_case_name=test_case_name,
                    test_result=result,
                    node=sender,
                )
            else:
                trex.create_udp_performance_message(
                    trex_result=trex_result,
                    test_case_name=test_case_name,
                    test_result=result,
                    node=sender,
                    packet_size_kbytes=pkt_size / 1024,
                )

            log.info(
                f"TRex {protocol} pkt={pkt_size}B  "
                f"TX={trex_result.tx_gbps:.3f} Gbps  "
                f"RX={trex_result.rx_gbps:.3f} Gbps  "
                f"loss={trex_result.loss_percent:.2f}%"
            )

    finally:
        # ------------------------------------------------------------------
        # 6. Always stop the server so DPDK resources are released
        # ------------------------------------------------------------------
        trex.stop_server()
