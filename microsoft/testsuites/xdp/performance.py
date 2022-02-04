# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from functools import partial
from time import sleep

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
from lisa.features import Sriov, Synthetic
from lisa.nic import NicInfo
from lisa.tools import Kill, Lscpu
from lisa.util.parallel import run_in_parallel
from microsoft.testsuites.xdp.common import (
    get_dropped_count,
    get_forwarded_count,
    get_xdpdump,
    remove_hugepage,
    set_hugepage,
)
from microsoft.testsuites.xdp.pktgen import Pktgen, PktgenResult
from microsoft.testsuites.xdp.xdpdump import BuildType

# the received packets must be at least 90%
_default_received_threshold = 0.9


@TestSuiteMetadata(
    area="xdp",
    category="performance",
    description="""
    This test suite is to validate XDP performance.
    """,
)
class XdpPerformance(TestSuite):
    @TestCaseMetadata(
        description="""
        This case tests the packet forwarded rate of the XDP TX forwarding on
        the single core Synthetic networking. The pktgen samples in Linux code
        base is used to generate packets.

        The minimum cpu count is 8, it makes sure the performance is won't too
        low.

        Three roles in this test environment, 1) sender is to send pckets, 2)
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
        pktgen = sender.tools[Pktgen]
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
        assert_that(validate_count / pktgen_result.sent_count).described_as(
            f"forwarded packets should be above {threshold*100}% of sent"
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
