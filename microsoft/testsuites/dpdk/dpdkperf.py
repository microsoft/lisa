from typing import Any, Dict, Tuple

from assertpy import assert_that

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
from lisa.tools import Lscpu
from lisa.util import constants
from microsoft.testsuites.dpdk.dpdkutil import (
    DpdkTestResources,
    SkippedException,
    UnsupportedPackageVersionException,
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
    TIMEOUT = 12000

    @TestCaseMetadata(
        description="""
        DPDK Performance: failsafe mode, minimal core count
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2, network_interface=Sriov(), min_nic_count=2, min_core_count=4
        ),
    )
    def perf_dpdk_failsafe_pmd_dual_core(
        self,
        environment: Environment,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:

        self._run_dpdk_perf_test("failsafe", environment, log, variables)

    @TestCaseMetadata(
        description="""
        DPDK Performance: failsafe mode, maximal core count, default queue settings
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
            min_nic_count=2,
            min_core_count=8,
        ),
    )
    def perf_dpdk_failsafe_pmd_multi_core(
        self,
        environment: Environment,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:

        self._run_dpdk_perf_test(
            "failsafe", environment, log, variables, use_max_cores=True
        )

    @TestCaseMetadata(
        description="""
        DPDK Performance: failsafe mode, maximal core count, default queue settings
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
            min_nic_count=2,
            min_core_count=48,
        ),
    )
    def perf_dpdk_failsafe_pmd_multi_core_huge_vm(
        self,
        environment: Environment,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:

        self._run_dpdk_perf_test(
            "failsafe", environment, log, variables, use_max_cores=True
        )

    @TestCaseMetadata(
        description="""
        DPDK Performance: failsafe mode, maximum core count, maximum tx/rx queues

        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2, network_interface=Sriov(), min_nic_count=2, min_core_count=8
        ),
    )
    def perf_dpdk_failsafe_pmd_multi_queue(
        self,
        environment: Environment,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:

        self._run_dpdk_perf_test(
            "failsafe", environment, log, variables, use_queues=True
        )

    @TestCaseMetadata(
        description="""
        DPDK Performance: failsafe mode, maximum core count, maximum tx/rx queues
        Run on a huge machine
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2, network_interface=Sriov(), min_nic_count=2, min_core_count=48
        ),
    )
    def perf_dpdk_failsafe_pmd_multi_queue_huge_vm(
        self,
        environment: Environment,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:

        self._run_dpdk_perf_test(
            "failsafe", environment, log, variables, use_queues=True
        )

    @TestCaseMetadata(
        description="""
        DPDK Performance: direct use of VF, minimal core count, default queues

        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2, network_interface=Sriov(), min_nic_count=2, min_core_count=4
        ),
    )
    def perf_dpdk_netvsc_pmd_dual_core(
        self,
        environment: Environment,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:
        self._validate_core_counts_are_equal(environment)
        self._run_dpdk_perf_test("netvsc", environment, log, variables)

    @TestCaseMetadata(
        description="""
        DPDK Performance: direct use of VF, maximum core count, default queues
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2, network_interface=Sriov(), min_nic_count=2, min_core_count=8
        ),
    )
    def perf_dpdk_netvsc_pmd_multi_core(
        self,
        environment: Environment,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:

        self._run_dpdk_perf_test(
            "netvsc", environment, log, variables, use_max_cores=True
        )

    @TestCaseMetadata(
        description="""
        DPDK Performance: direct use of VF, maximum core count, default queues
        Run on a big VM
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2, network_interface=Sriov(), min_nic_count=2, min_core_count=48
        ),
    )
    def perf_dpdk_netvsc_pmd_multi_core_huge_vm(
        self,
        environment: Environment,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:

        self._run_dpdk_perf_test(
            "netvsc", environment, log, variables, use_max_cores=True
        )

    @TestCaseMetadata(
        description="""
        DPDK Performance: direct use of VF, maximum core count, maximum tx/rx queues
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2, network_interface=Sriov(), min_nic_count=2, min_core_count=8
        ),
    )
    def perf_dpdk_netvsc_pmd_multi_queue(
        self,
        environment: Environment,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:

        self._run_dpdk_perf_test("netvsc", environment, log, variables, use_queues=True)

    @TestCaseMetadata(
        description="""
        DPDK Performance: direct use of VF, maximum core count, maximum tx/rx queues,
        Run on a huge machine
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2, network_interface=Sriov(), min_nic_count=2, min_core_count=48
        ),
    )
    def perf_dpdk_netvsc_pmd_multi_queue_huge_vm(
        self,
        environment: Environment,
        log: Logger,
        variables: Dict[str, Any],
    ) -> None:

        self._run_dpdk_perf_test("netvsc", environment, log, variables, use_queues=True)

    def _run_dpdk_perf_test(
        self,
        pmd: str,
        environment: Environment,
        log: Logger,
        variables: Dict[str, Any],
        use_max_cores: bool = False,
        use_queues: bool = False,
    ) -> None:
        # run build + validation to populate results
        max_core_count = self._validate_core_counts_are_equal(environment)
        if use_max_cores:
            core_count_argument = max_core_count
        else:
            core_count_argument = 0  # expected default, test will use 2 cores.

        try:
            if use_queues:
                send_kit, receive_kit = verify_dpdk_send_receive_multi_txrx_queue(
                    environment, log, variables, pmd
                )
            else:
                send_kit, receive_kit = verify_dpdk_send_receive(
                    environment, log, variables, pmd, core_count_argument
                )
        except UnsupportedPackageVersionException as err:
            raise SkippedException(err)

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
        sender_fields["tx_pps_average"] = sender.get_mean_tx_pps()
        sender_fields["tx_pps_minimum"] = sender.get_min_tx_pps()

        # receive side fields
        receiver = receive_kit.testpmd
        receiver_fields["role"] = "receiver/forwarder"
        receiver_fields["rx_pps_maximum"] = receiver.get_max_rx_pps()
        receiver_fields["rx_pps_average"] = receiver.get_mean_rx_pps()
        receiver_fields["rx_pps_minimum"] = receiver.get_min_rx_pps()
        receiver_fields["fwd_pps_maximum"] = receiver.get_max_tx_pps()
        receiver_fields["fwd_pps_average"] = receiver.get_mean_tx_pps()
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

    def _validate_core_counts_are_equal(self, environment: Environment) -> int:
        core_counts = [
            n.tools[Lscpu].get_core_count() for n in environment.nodes.list()
        ]

        assert_that(core_counts).described_as(
            "Nodes contain different core counts, DPDK Suite expects sender "
            "and receiver to have same core count."
        ).contains_only(core_counts[0])
        return core_counts[0]
