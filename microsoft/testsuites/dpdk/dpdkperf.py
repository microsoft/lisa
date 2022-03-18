from typing import Any, Dict, Tuple

from lisa import (
    Logger,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    notifier,
    simple_requirement,
)
from lisa.environment import Environment
from lisa.features import Sriov
from lisa.messages import NetworkPPSPerformanceMessage, create_message
from lisa.util import constants
from microsoft.testsuites.dpdk.dpdkutil import (
    DpdkTestResources,
    verify_dpdk_send_receive,
)


@TestSuiteMetadata(
    area="dpdk",
    category="performance",
    description="""
    This test suite is to validate DPDK performance
    """,
)
class DpdkPerformance(TestSuite):
    TIMEOUT = 12000

    @TestCaseMetadata(
        description="""
        This test case gathers performance data for dpdk send-recv-fwd: failsafe pmd
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_dpdk_failsafe(
        self,
        environment: Environment,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:
        self._run_dpdk_perf_test("failsafe", environment, log, variables)

    @TestCaseMetadata(
        description="""
        This test case gathers performance data for dpdk send-recv-fwd: netvsc pmd
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_dpdk_netvsc(
        self,
        environment: Environment,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:
        self._run_dpdk_perf_test("netvsc", environment, log, variables)

    def _run_dpdk_perf_test(
        self, pmd: str, environment: Environment, log: Logger, variables: Dict[str, Any]
    ) -> None:
        # run build + validation to populate results
        send_kit, receive_kit = verify_dpdk_send_receive(
            environment, log, variables, pmd
        )

        # gather the performance data into message format
        result_messages = self._create_pps_performance_results(
            send_kit, receive_kit, environment, f"perf_dpdk_{pmd}"
        )

        # pass result messages to notifier
        for message in result_messages:
            notifier.notify(message)

    def _create_pps_performance_results(
        self,
        send_kit: DpdkTestResources,
        receive_kit: DpdkTestResources,
        environment: Environment,
        test_case_name: str,
    ) -> Tuple[NetworkPPSPerformanceMessage, NetworkPPSPerformanceMessage]:
        sender_fields: Dict[str, Any] = {}
        receiver_fields: Dict[str, Any] = {}

        # shared results fields
        for result_fields in [sender_fields, receiver_fields]:
            result_fields["tool"] = constants.NETWORK_PERFORMANCE_TOOL_DPDK_TESTPMD
            result_fields["test_type"] = "performance"

        # send side fields
        sender = send_kit.testpmd
        sender_fields["role"] = "sender"
        sender_fields["tx_pps_maximum"] = sender.get_max_tx_pps()
        sender_fields["tx_pps_average"] = sender.get_average_tx_pps()
        sender_fields["tx_pps_minimum"] = sender.get_min_tx_pps()

        # receive side fields
        receiver = receive_kit.testpmd
        receiver_fields["role"] = "receiver/forwarder"
        receiver_fields["rx_pps_maximum"] = receiver.get_max_rx_pps()
        receiver_fields["rx_pps_average"] = receiver.get_average_rx_pps()
        receiver_fields["rx_pps_minimum"] = receiver.get_min_rx_pps()
        receiver_fields["fwd_pps_maximum"] = receiver.get_max_tx_pps()
        receiver_fields["fwd_pps_average"] = receiver.get_average_tx_pps()
        receiver_fields["fwd_pps_minimum"] = receiver.get_min_tx_pps()

        send_results = create_message(
            NetworkPPSPerformanceMessage,
            send_kit.node,
            environment,
            test_case_name,
            sender_fields,
        )
        receive_results = create_message(
            NetworkPPSPerformanceMessage,
            receive_kit.node,
            environment,
            test_case_name,
            receiver_fields,
        )

        return send_results, receive_results
