from typing import Any, Dict, Tuple

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    notifier,
    simple_requirement,
)
from lisa.features import Gpu, Infiniband, Sriov
from lisa.messages import (
    NetworkPPSPerformanceMessage,
    TransportProtocol,
    create_perf_message,
)
from lisa.testsuite import TestResult
from lisa.tools import Lscpu
from lisa.tools.hugepages import HugePageSize
from lisa.util import constants
from microsoft.testsuites.dpdk.common import force_dpdk_default_source
from microsoft.testsuites.dpdk.dpdkutil import (
    DpdkTestResources,
    SkippedException,
    UnsupportedPackageVersionException,
    do_parallel_cleanup,
    verify_dpdk_build,
    verify_dpdk_l3fwd_ntttcp_tcp,
    verify_dpdk_send_receive,
    verify_dpdk_send_receive_multi_txrx_queue,
)


@TestSuiteMetadata(
    area="dpdk",
    category="performance",
    description="""
    This test suite is to validate DPDK performance
    """,
)
class DpdkPerformance(TestSuite):
    @TestCaseMetadata(
        description="""
        DPDK Performance: failsafe mode, minimal core count
        """,
        priority=3,
        requirement=simple_requirement(
            min_core_count=16,
            min_count=1,
            network_interface=Sriov(),
            min_nic_count=2,
            unsupported_features=[Gpu, Infiniband],
        ),
    )
    def perf_dpdk_send_only_failsafe_pmd(
        self,
        node: Node,
        result: TestResult,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:
        sender_kit = verify_dpdk_build(
            node, log, variables, "failsafe", HugePageSize.HUGE_2MB, result=result
        )
        sender_fields: Dict[str, Any] = {}
        test_case_name = result.runtime_data.metadata.name
        # shared results fields

        sender_fields["tool"] = constants.NETWORK_PERFORMANCE_TOOL_DPDK_TESTPMD
        sender_fields["test_type"] = "performance"

        # send side fields
        sender = sender_kit.testpmd
        sender_fields["role"] = "sender"
        sender_fields["tx_pps_maximum"] = sender.get_max_tx_pps()
        sender_fields["tx_pps_average"] = sender.get_mean_tx_pps()
        sender_fields["tx_pps_minimum"] = sender.get_min_tx_pps()

        send_results = create_perf_message(
            NetworkPPSPerformanceMessage,
            node,
            result,
            test_case_name,
            sender_fields,
        )
        notifier.notify(send_results)

    @TestCaseMetadata(
        description="""
        DPDK Performance: failsafe mode, minimal core count
        """,
        priority=3,
        requirement=simple_requirement(
            min_core_count=16,
            min_count=1,
            network_interface=Sriov(),
            min_nic_count=2,
            unsupported_features=[Gpu, Infiniband],
        ),
    )
    def perf_dpdk_send_only_netvsc_pmd(
        self,
        node: Node,
        result: TestResult,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:
        sender_kit = verify_dpdk_build(
            node, log, variables, "netvsc", HugePageSize.HUGE_2MB, result=result
        )
        sender_fields: Dict[str, Any] = {}
        test_case_name = result.runtime_data.metadata.name
        # shared results fields

        sender_fields["tool"] = constants.NETWORK_PERFORMANCE_TOOL_DPDK_TESTPMD
        sender_fields["test_type"] = "performance"

        # send side fields
        sender = sender_kit.testpmd
        sender_fields["role"] = "sender"
        sender_fields["tx_pps_maximum"] = sender.get_max_tx_pps()
        sender_fields["tx_pps_average"] = sender.get_mean_tx_pps()
        sender_fields["tx_pps_minimum"] = sender.get_min_tx_pps()

        send_results = create_perf_message(
            NetworkPPSPerformanceMessage,
            node,
            result,
            test_case_name,
            sender_fields,
        )
        notifier.notify(send_results)

    @TestCaseMetadata(
        description="""
        DPDK Performance: failsafe mode, minimal core count
        """,
        priority=3,
        requirement=simple_requirement(
            min_core_count=8,
            min_count=2,
            network_interface=Sriov(),
            min_nic_count=2,
            unsupported_features=[Gpu, Infiniband],
        ),
    )
    def perf_dpdk_minimal_failsafe_pmd(
        self,
        result: TestResult,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:
        self._run_dpdk_perf_test("failsafe", result, log, variables)

    @TestCaseMetadata(
        description="""
        DPDK Performance: netvsc mode, minimal core count
        """,
        priority=3,
        requirement=simple_requirement(
            min_core_count=8,
            min_count=2,
            network_interface=Sriov(),
            min_nic_count=2,
            unsupported_features=[Gpu, Infiniband],
        ),
    )
    def perf_dpdk_minimal_netvsc_pmd(
        self,
        result: TestResult,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:
        self._run_dpdk_perf_test("netvsc", result, log, variables)

    @TestCaseMetadata(
        description="""
        DPDK Performance: failsafe mode, muliple tx/rx queues

        """,
        priority=3,
        requirement=simple_requirement(
            min_core_count=16,
            min_count=2,
            network_interface=Sriov(),
            min_nic_count=2,
            unsupported_features=[Gpu, Infiniband],
        ),
    )
    def perf_dpdk_multi_queue_failsafe_pmd(
        self,
        result: TestResult,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:
        self._run_dpdk_perf_test(
            "failsafe",
            result,
            log,
            variables,
            use_queues=True,
        )

    @TestCaseMetadata(
        description="""
        DPDK Performance: direct use of VF, multiple tx/rx queues
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
            min_nic_count=2,
            min_core_count=16,
            unsupported_features=[Gpu, Infiniband],
        ),
    )
    def perf_dpdk_multi_queue_netvsc_pmd(
        self,
        result: TestResult,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:
        self._run_dpdk_perf_test(
            "netvsc",
            result,
            log,
            variables,
            use_queues=True,
        )

    @TestCaseMetadata(
        description=(
            """
                Run the L3 forwarding perf test for DPDK.
                This test creates a DPDK port forwarding setup between
                two NICs on the same VM. It forwards packets from a sender on
                subnet_a to a receiver on subnet_b. Without l3fwd,
                packets will not be able to jump the subnets.  This imitates
                a network virtual appliance setup, firewall, or other data plane
                tool for managing network traffic with DPDK.
        """
        ),
        priority=3,
        requirement=simple_requirement(
            min_core_count=8,
            min_count=3,
            min_nic_count=3,
            network_interface=Sriov(),
            unsupported_features=[Gpu, Infiniband],
        ),
    )
    def perf_dpdk_l3fwd_ntttcp_tcp(
        self, environment: Environment, log: Logger, variables: Dict[str, Any]
    ) -> None:
        force_dpdk_default_source(variables)
        verify_dpdk_l3fwd_ntttcp_tcp(
            environment,
            log,
            variables,
            HugePageSize.HUGE_2MB,
            pmd="netvsc",
            is_perf_test=True,
        )

    def _run_dpdk_perf_test(
        self,
        pmd: str,
        test_result: TestResult,
        log: Logger,
        variables: Dict[str, Any],
        use_queues: bool = False,
    ) -> None:
        environment = test_result.environment
        assert environment, "fail to get environment from testresult"

        # run build + validation to populate results
        self._validate_core_counts_are_equal(test_result)
        try:
            if use_queues:
                send_kit, receive_kit = verify_dpdk_send_receive_multi_txrx_queue(
                    environment,
                    log,
                    variables,
                    pmd,
                )
            else:
                send_kit, receive_kit = verify_dpdk_send_receive(
                    environment,
                    log,
                    variables,
                    pmd,
                    HugePageSize.HUGE_2MB,
                )
        except UnsupportedPackageVersionException as err:
            raise SkippedException(err)

        # gather the performance data into message format
        result_messages = self._create_pps_performance_results(
            send_kit, receive_kit, test_result
        )

        # pass result messages to notifier
        for msg in result_messages:
            notifier.notify(msg)

    def _create_pps_performance_results(
        self,
        send_kit: DpdkTestResources,
        receive_kit: DpdkTestResources,
        test_result: TestResult,
    ) -> Tuple[NetworkPPSPerformanceMessage, NetworkPPSPerformanceMessage]:
        sender_fields: Dict[str, Any] = {}
        receiver_fields: Dict[str, Any] = {}
        test_case_name = test_result.runtime_data.metadata.name

        # shared results fields
        for result_fields in [sender_fields, receiver_fields]:
            result_fields["tool"] = constants.NETWORK_PERFORMANCE_TOOL_DPDK_TESTPMD
            result_fields["test_type"] = "performance"
            result_fields["protocol_type"] = TransportProtocol.Udp

        # send side fields
        sender = send_kit.testpmd
        sender_fields["role"] = "sender"
        sender_fields["tx_pps_maximum"] = sender.get_max_tx_pps()
        sender_fields["tx_pps_average"] = sender.get_mean_tx_pps()
        sender_fields["tx_pps_minimum"] = sender.get_min_tx_pps()

        # receive side fields
        receiver = receive_kit.testpmd
        receiver_fields["role"] = "receiver/forwarder"
        receiver_fields["rx_pps_maximum"] = receiver.get_max_rx_pps()
        receiver_fields["rx_pps_average"] = receiver.get_mean_rx_pps()
        receiver_fields["rx_pps_minimum"] = receiver.get_min_rx_pps()

        send_results = create_perf_message(
            NetworkPPSPerformanceMessage,
            send_kit.node,
            test_result,
            test_case_name,
            sender_fields,
        )
        receive_results = create_perf_message(
            NetworkPPSPerformanceMessage,
            receive_kit.node,
            test_result,
            test_case_name,
            receiver_fields,
        )

        return send_results, receive_results

    def _validate_core_counts_are_equal(self, test_result: TestResult) -> None:
        environment = test_result.environment
        assert environment, "fail to get environment from testresult"

        core_counts = [
            n.tools[Lscpu].get_core_count() for n in environment.nodes.list()
        ]

        assert_that(core_counts).described_as(
            "Nodes contain different core counts, DPDK Suite expects sender "
            "and receiver to have same core count."
        ).contains_only(core_counts[0])

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        do_parallel_cleanup(environment)
