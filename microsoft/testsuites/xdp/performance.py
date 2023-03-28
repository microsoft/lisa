# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import inspect
from functools import partial
from time import sleep
from typing import Any, List, Type

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    UnsupportedKernelException,
    simple_requirement,
)
from lisa.executable import Tool
from lisa.features import Sriov, Synthetic
from lisa.nic import NicInfo
from lisa.testsuite import TestResult
from lisa.tools import Firewall, Kill, Lagscope, Lscpu, Ntttcp
from lisa.util.parallel import run_in_parallel
from microsoft.testsuites.performance.common import (
    calculate_middle_average,
    perf_ntttcp,
)
from microsoft.testsuites.xdp.common import (
    get_dropped_count,
    get_forwarded_count,
    get_xdpdump,
    remove_hugepage,
    set_hugepage,
)
from microsoft.testsuites.xdp.pktgen import Pktgen, PktgenResult
from microsoft.testsuites.xdp.xdpdump import BuildType, XdpDump

# the received packets must be at least 90%
_default_received_threshold = 0.9
# the xdp latency shouldn't take more than 40% time.
_default_latency_threshold = 1.4


@TestSuiteMetadata(
    area="xdp",
    category="performance",
    description="""
    This test suite is to validate XDP performance.
    """,
)
class XdpPerformance(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        for node in environment.nodes.list():
            node.tools[Firewall].stop()

    @TestCaseMetadata(
        description="""
        This case tests the packet forwarded rate of the XDP TX forwarding on
        the single core Synthetic networking. The pktgen samples in Linux code
        base is used to generate packets.

        The minimum cpu count is 8, it makes sure the performance is won't too
        low.

        Three roles in this test environment, 1) sender is to send packets, 2)
        the forwarder is to forward packets to receiver, 3) and the receiver is
        used to receive packets and drop.

        Finally, it checks how many packets arrives to the forwarder or
        receiver. If it's lower than 90%, the test fails. Note, it counts the
        rx_xdp_tx_xmit (mlx5), rx_xdp_tx (mlx4), or dropped count for synthetic
        nic.
        """,
        priority=3,
        requirement=simple_requirement(
            min_nic_count=2,
            min_count=3,
            min_core_count=8,
            network_interface=Synthetic(),
        ),
    )
    def perf_xdp_tx_forward_singlecore_synthetic(
        self, environment: Environment, log: Logger
    ) -> None:
        self._execute_tx_forward_test(environment, log)

    @TestCaseMetadata(
        description="""
        This case tests the packet forwarded rate of XDP TX forwarding on the
        single core SRIOV networking.

        Refer to perf_xdp_tx_forward_singlecore_synthetic for more details.
        """,
        priority=3,
        requirement=simple_requirement(
            min_nic_count=2, min_count=3, min_core_count=8, network_interface=Sriov()
        ),
    )
    def perf_xdp_tx_forward_singlecore_sriov(
        self, environment: Environment, log: Logger
    ) -> None:
        self._execute_tx_forward_test(environment, log)

    @TestCaseMetadata(
        description="""
        This case tests the packet forwarded rate of XDP TX forwarding on the
        multi core Syntethic networking.

        Refer to perf_xdp_tx_forward_singlecore_synthetic for more details.
        """,
        priority=3,
        requirement=simple_requirement(
            min_nic_count=2,
            min_count=3,
            min_core_count=8,
            network_interface=Synthetic(),
        ),
    )
    def perf_xdp_tx_forward_multicore_synthetic(
        self, environment: Environment, log: Logger
    ) -> None:
        self._execute_tx_forward_test(environment, log, is_multi_threads=True)

    @TestCaseMetadata(
        description="""
        This case tests the packet forwarded rate of XDP TX forwarding on the
        multi core SRIOV networking.

        Refer to perf_xdp_tx_forward_singlecore_synthetic for more details.

        The threshold of this test is lower than standard, it's 85%. Because the
        UDP packets count is big in this test scenario, and easy to lost.
        """,
        priority=3,
        requirement=simple_requirement(
            min_nic_count=2, min_count=3, min_core_count=8, network_interface=Sriov()
        ),
    )
    def perf_xdp_tx_forward_multicore_sriov(
        self, environment: Environment, log: Logger
    ) -> None:
        self._execute_tx_forward_test(
            environment, log, is_multi_threads=True, threshold=0.85
        )

    @TestCaseMetadata(
        description="""
        This case tests the XDP drop performance by measuring Packets Per Second
        (PPS) and received rate with multiple send threads.

        * If the received packets rate is lower than 90% the test case fails.
        * If the PPS is lower than 1M, the test case fails.
        """,
        priority=3,
        requirement=simple_requirement(
            min_nic_count=2,
            min_count=2,
            min_core_count=8,
            network_interface=Sriov(),
        ),
    )
    def perf_xdp_rx_drop_multithread_sriov(
        self, environment: Environment, log: Logger
    ) -> None:
        self._execute_rx_drop_test(
            environment,
            True,
            log,
        )

    @TestCaseMetadata(
        description="""
        This case tests the XDP drop performance by measuring Packets Per Second
        (PPS) and received rate with single send thread.

        see details from perf_xdp_rx_drop_multithread_sriov.
        """,
        priority=3,
        requirement=simple_requirement(
            min_nic_count=2, min_count=2, min_core_count=8, network_interface=Sriov()
        ),
    )
    def perf_xdp_rx_drop_singlethread_sriov(
        self, environment: Environment, log: Logger
    ) -> None:
        self._execute_rx_drop_test(
            environment,
            False,
            log,
        )

    @TestCaseMetadata(
        description="""
        This case compare and record latency impact of XDP component.

        The test use lagscope to send tcp packets. And then compare the latency
        with/without XDP component. If the gap is more than 40%, the test case
        fails.
        """,
        priority=3,
        requirement=simple_requirement(
            min_nic_count=2, min_count=2, min_core_count=8, network_interface=Sriov()
        ),
    )
    def perf_xdp_lagscope_latency(self, result: TestResult, log: Logger) -> None:
        self._execute_latency_test(
            result,
            Lagscope,
            log,
        )

    @TestCaseMetadata(
        description="""
        This case compare and record latency impact of XDP component.

        The test use ntttcp to send tcp packets. And then compare the latency
        with/without XDP component. If the gap is more than 40%, the test case
        fails.
        """,
        priority=3,
        requirement=simple_requirement(
            min_nic_count=2, min_count=2, min_core_count=8, network_interface=Sriov()
        ),
    )
    def perf_xdp_ntttcp_latency(self, result: TestResult, log: Logger) -> None:
        self._execute_latency_test(
            result,
            Ntttcp,
            log,
        )

    def _execute_latency_test(
        self,
        test_result: TestResult,
        tool_type: Type[Tool],
        log: Logger,
    ) -> None:
        environment = test_result.environment
        assert environment, "fail to get environment from testresult"
        server = environment.nodes[0]
        client = environment.nodes[1]

        server_xdpdump = get_xdpdump(server)
        server_xdpdump.make_by_build_type(BuildType.PERF)
        server_nic = server.nics.get_nic_by_index(1)

        # the latency is not stable in cloud environment, test multiple times
        # and aggregate the result.
        tested_runs = 5
        latency_without_xdp: List[float] = []
        latency_with_xdp: List[float] = []

        for _ in range(tested_runs):
            latency_without_xdp.append(
                self._send_packets_for_latency(server, client, test_result, tool_type)
            )

            try:
                server_xdpdump.start_async(nic_name=server_nic.upper, timeout=0)
                latency_with_xdp.append(
                    self._send_packets_for_latency(
                        server, client, test_result, tool_type
                    )
                )
            finally:
                server_kill = server.tools[Kill]
                server_kill.by_name("xdpdump")
        final_without_xdp = calculate_middle_average(latency_without_xdp)
        final_with_xdp = calculate_middle_average(latency_with_xdp)

        log.info(
            f"Latency with XDP: {final_with_xdp}us, "
            f"without XDP: {final_without_xdp}us. "
            f"Raw with XDP: {latency_with_xdp}, "
            f"without XDP: {latency_without_xdp}. "
        )
        assert_that(final_with_xdp / final_without_xdp).described_as(
            f"The XDP latency: {final_with_xdp}us shouldn't slower 40% than "
            f"the normal latency: {final_without_xdp}us."
        ).is_less_than_or_equal_to(_default_latency_threshold)

    def _send_packets_for_latency(
        self,
        server: Node,
        client: Node,
        test_result: TestResult,
        tool_type: Type[Tool],
    ) -> float:
        assert_that(tool_type).described_as("the tool is not supported").is_in(
            Lagscope, Ntttcp
        )

        # mypy doesn't work with generic type method "get". So use a
        # intermidiate variable tools to store it.
        tools: List[Any] = run_in_parallel(
            [
                partial(server.tools.get, tool_type),
                partial(client.tools.get, tool_type),
            ]
        )

        server_nic = server.nics.get_nic_by_index(1)

        if tool_type is Lagscope:
            server_lagscope: Lagscope = tools[0]
            client_lagscope: Lagscope = tools[1]
            try:
                run_in_parallel(
                    [server_lagscope.set_busy_poll, client_lagscope.set_busy_poll]
                )
                server_lagscope.run_as_server_async(ip=server_nic.ip_addr)

                result = client_lagscope.run_as_client(server_ip=server_nic.ip_addr)
                lagscope_messages = client_lagscope.create_latency_performance_messages(
                    result=result,
                    test_case_name=inspect.stack()[2].function,
                    test_result=test_result,
                )

                assert lagscope_messages
                assert_that(len(lagscope_messages)).described_as(
                    "at least one message is necessary"
                ).is_greater_than(0)
                return float(
                    sum(x.average_latency_us for x in lagscope_messages)
                    / len(lagscope_messages)
                )
            finally:
                for lagscope in [server_lagscope, client_lagscope]:
                    lagscope.kill()
                    lagscope.restore_busy_poll()
        else:
            ntttcp_messages = perf_ntttcp(
                test_result=test_result,
                udp_mode=False,
                connections=[1],
                test_case_name=inspect.stack()[2].function,
            )

            return float(
                # The type is always TCP message, because the above line set udp
                # to False. Ignore type error here, because UDP message has no
                # latency metrics.
                sum(x.latency_us for x in ntttcp_messages)  # type: ignore
                / len(ntttcp_messages)
            )

    def _execute_rx_drop_test(
        self,
        environment: Environment,
        is_multi_thread: bool,
        log: Logger,
        threshold: float = _default_received_threshold,
    ) -> None:
        sender = environment.nodes[0]
        receiver = environment.nodes[1]

        # install pktgen on sender, and xdpdump on receiver.
        try:
            tools: List[Any] = []
            tools.append(get_xdpdump(receiver))
            tools.append(sender.tools[Pktgen])
        except UnsupportedKernelException as identifier:
            raise SkippedException(identifier)

        # type annotations
        xdpdump: XdpDump = tools[0]
        pktgen: Pktgen = tools[1]

        sender_nic = sender.nics.get_nic_by_index(1)
        receiver_nic = receiver.nics.get_nic_by_index(1)

        xdpdump.make_by_build_type(build_type=BuildType.PERF_DROP)

        original_dropped_count = get_dropped_count(
            node=receiver,
            nic=receiver_nic,
            previous_count=0,
            log=log,
        )
        try:
            xdpdump.start_async(nic_name=receiver_nic.upper, timeout=0)

            pktgen_result = self._send_packets(
                is_multi_thread, sender, pktgen, sender_nic, receiver_nic
            )

            self._wait_packets_proceeded(
                log, receiver, receiver_nic, original_dropped_count
            )
        finally:
            receiver_kill = receiver.tools[Kill]
            receiver_kill.by_name("xdpdump")

        # capture stats to calculate delta
        dropped_count = get_dropped_count(
            node=receiver,
            nic=receiver_nic,
            previous_count=original_dropped_count,
            log=log,
        )

        log.debug(
            f"sender pktgen result: {pktgen_result}, "
            f"dropped on receiver: {dropped_count}"
        )

        self._check_threshold(
            pktgen_result.sent_count, dropped_count, threshold, "dropped packets"
        )

        assert_that(pktgen_result.pps).described_as(
            "pps must be greater than 1M."
        ).is_greater_than_or_equal_to(1000000)

    def _execute_tx_forward_test(
        self,
        environment: Environment,
        log: Logger,
        is_multi_threads: bool = False,
        threshold: float = _default_received_threshold,
    ) -> None:
        sender = environment.nodes[0]
        forwarder = environment.nodes[1]
        receiver = environment.nodes[2]

        # install pktgen on sender
        try:
            pktgen = sender.tools[Pktgen]
        except UnsupportedKernelException as identifier:
            raise SkippedException(identifier)
        # install xdp dump on forwarder and receiver
        forwarder_xdpdump, receiver_xdpdump = run_in_parallel(
            [
                partial(get_xdpdump, forwarder),
                partial(get_xdpdump, receiver),
            ],
            log=log,
        )
        sender_nic = sender.nics.get_nic_by_index(1)
        forwarder_nic = forwarder.nics.get_nic_by_index(1)
        receiver_nic = receiver.nics.get_nic_by_index(1)

        run_in_parallel(
            [
                partial(
                    forwarder_xdpdump.make_on_forwarder_role,
                    forwarder_nic=forwarder_nic,
                    receiver_nic=receiver_nic,
                ),
                partial(
                    receiver_xdpdump.make_by_build_type, build_type=BuildType.PERF_DROP
                ),
            ]
        )

        # capture existing stats to calculate delta
        original_forwarded_count = get_forwarded_count(
            node=forwarder,
            nic=forwarder_nic,
            previous_count=0,
            log=log,
        )
        original_dropped_count = get_dropped_count(
            node=receiver,
            nic=receiver_nic,
            previous_count=0,
            log=log,
        )

        try:
            # start xdpdump
            forwarder_xdpdump.start_async(nic_name=forwarder_nic.upper, timeout=0)
            receiver_xdpdump.start_async(nic_name=receiver_nic.upper, timeout=0)

            pktgen_result = self._send_packets(
                is_multi_threads, sender, pktgen, sender_nic, forwarder_nic
            )

            self._wait_packets_proceeded(
                log, receiver, receiver_nic, original_dropped_count
            )

        finally:
            # kill xdpdump processes.
            forwarder_kill = forwarder.tools[Kill]
            forwarder_kill.by_name("xdpdump")
            receiver_kill = receiver.tools[Kill]
            receiver_kill.by_name("xdpdump")

        # capture stats to calculate delta
        dropped_count = get_dropped_count(
            node=receiver,
            nic=receiver_nic,
            previous_count=original_dropped_count,
            log=log,
        )
        forwarded_count = get_forwarded_count(
            node=forwarder,
            nic=forwarder_nic,
            previous_count=original_forwarded_count,
            log=log,
        )

        # In some nodes like synthetic nic, there is no forward counter,
        # so count it by dropped count.
        validate_count = forwarded_count
        if not validate_count:
            validate_count = dropped_count

        log.debug(
            f"sender pktgen result: {pktgen_result}, "
            f"on forwarder: {forwarded_count}, "
            f"on receiver: {dropped_count}"
        )

        self._check_threshold(
            pktgen_result.sent_count, validate_count, threshold, "forwarded packets"
        )

    def _check_threshold(
        self, expected_count: int, actual_count: int, threshold: float, packet_name: str
    ) -> None:
        assert_that(actual_count / expected_count).described_as(
            f"{packet_name} rate should be above the threshold. "
            f"expected count: {expected_count}, actual count: {actual_count}"
        ).is_greater_than_or_equal_to(threshold)

    def _wait_packets_proceeded(
        self, log: Logger, receiver: Node, receiver_nic: NicInfo, original_count: int
    ) -> int:
        # wait until the forwarded count is not increased, it means there is
        # no more packets in queue.
        current_count = 0
        delta_count = 1
        while delta_count:
            sleep(1)
            previous_count = current_count
            current_count = get_dropped_count(
                node=receiver,
                nic=receiver_nic,
                previous_count=original_count,
                log=log,
            )
            delta_count = current_count - previous_count
            message = f"received {delta_count} new dropped packets in the 0.5 second."
            if delta_count > 0:
                message += " keep checking."
            log.debug(message)
        return previous_count

    def _send_packets(
        self,
        is_multi_threads: bool,
        sender: Node,
        pktgen: Pktgen,
        sender_nic: NicInfo,
        forwarder_nic: NicInfo,
    ) -> PktgenResult:
        # send packets use the second nic to make sure the performance is not
        # impact by LISA.
        forwarder_ip = forwarder_nic.ip_addr
        forwarder_mac = forwarder_nic.mac_addr

        if is_multi_threads:
            lscpu = sender.tools[Lscpu]
            # max 8 thread to prevent too big concurrency
            thread_count = int(min(lscpu.get_core_count(), 8))
        else:
            thread_count = 1

        try:
            set_hugepage(sender)
            result = pktgen.send_packets(
                destination_ip=forwarder_ip,
                destination_mac=forwarder_mac,
                nic_name=sender_nic.upper,
                thread_count=thread_count,
            )
        finally:
            remove_hugepage(sender)
        return result
