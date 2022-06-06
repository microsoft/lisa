# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import time
from typing import Any, cast

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.features import HibernationEnabled, Sriov, Synthetic
from lisa.testsuite import simple_requirement
from lisa.tools import Date, Hwclock, StressNg
from lisa.util.perf_timer import create_timer
from microsoft.testsuites.power.common import (
    cleanup_env,
    is_distro_supported,
    run_network_workload,
    run_storage_workload,
    verify_hibernation,
)


@TestSuiteMetadata(
    area="power",
    category="functional",
    description="""
        This test suite is to test hibernation in guest VM.
    """,
)
class Power(TestSuite):
    @TestCaseMetadata(
        description="""
            This case is to verify vm hibernation with synthetic network.

            Steps,
            1. Install HibernationSetup tool to prepare prerequisite for vm
             hibernation.
            2. Get nics info before hibernation.
            3. Hibernate vm.
            4. Check vm is inaccessible.
            5. Resume vm by starting vm.
            6. Check vm hibernation successfully by checking keywords in dmesg.
            6. Get nics info after hibernation.
            7. Fail the case if nics count and info changes after vm resume.
        """,
        priority=3,
        requirement=simple_requirement(
            network_interface=Synthetic(),
            supported_features=[HibernationEnabled()],
        ),
    )
    def verify_hibernation_synthetic_network(
        self, environment: Environment, log: Logger
    ) -> None:
        node = cast(RemoteNode, environment.nodes[0])
        is_distro_supported(node)
        verify_hibernation(node, log)

    @TestCaseMetadata(
        description="""
            This case is to verify vm hibernation with sriov network.
            It has the same steps with verify_hibernation_synthetic_network.
        """,
        priority=3,
        requirement=simple_requirement(
            network_interface=Sriov(),
            supported_features=[HibernationEnabled()],
        ),
    )
    def verify_hibernation_sriov_network(
        self, environment: Environment, log: Logger
    ) -> None:
        node = cast(RemoteNode, environment.nodes[0])
        is_distro_supported(node)
        verify_hibernation(node, log)

    @TestCaseMetadata(
        description="""
            This case is to verify vm time sync working after hibernation.

            Steps,
            1. Reset time using hwclock as 1 year after current date.
            2. Hibernate and resume vm.
            3. Check vm time sync correctly.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[HibernationEnabled()],
        ),
    )
    def verify_hibernation_time_sync(
        self, environment: Environment, log: Logger
    ) -> None:
        node = cast(RemoteNode, environment.nodes[0])
        is_distro_supported(node)
        date = node.tools[Date]
        current_date = date.current()
        newdate = current_date.replace(year=current_date.year + 1)

        hwclock = node.tools[Hwclock]
        hwclock.set_datetime(newdate)

        changed_date_before_hb = hwclock.get()
        assert_that(
            changed_date_before_hb.year - current_date.year,
            "fail to reset time",
        ).is_equal_to(1)
        verify_hibernation(node, log)
        timeout = 600
        timer = create_timer()
        while timeout > timer.elapsed(False):
            changed_date_after_hb = hwclock.get()
            if changed_date_after_hb.year == current_date.year:
                break
            time.sleep(2)
        assert_that(
            changed_date_after_hb.year,
            "after hb, timesync doesn't work",
        ).is_equal_to(current_date.year)

    @TestCaseMetadata(
        description="""
            This case is to verify hibernation with network workload.

            Steps,
            1. Run iperf3 network benchmark, make sure no issues.
            2. Hibernate and resume vm.
            3. Run iperf3 network benchmark, make sure no issues.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            supported_features=[HibernationEnabled()],
        ),
    )
    def verify_hibernation_with_network_workload(
        self, environment: Environment, log: Logger
    ) -> None:
        client_node = cast(RemoteNode, environment.nodes[0])
        is_distro_supported(client_node)
        run_network_workload(environment)
        verify_hibernation(client_node, log)
        run_network_workload(environment)

    @TestCaseMetadata(
        description="""
            This case is to verify hibernation with storage workload.

            Steps,
            1. Run fio benchmark, make sure no issues.
            2. Hibernate and resume vm.
            3. Run fio benchmark, make sure no issues.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[HibernationEnabled()],
        ),
    )
    def verify_hibernation_with_storage_workload(
        self, environment: Environment, log: Logger
    ) -> None:
        node = cast(RemoteNode, environment.nodes[0])
        is_distro_supported(node)
        run_storage_workload(node)
        verify_hibernation(node, log)
        run_storage_workload(node)

    @TestCaseMetadata(
        description="""
            This case is to verify hibernation with memory workload.

            Steps,
            1. Run stress-ng benchmark, make sure no issues.
            2. Hibernate and resume vm.
            3. Run stress-ng benchmark, make sure no issues.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[HibernationEnabled()],
        ),
    )
    def verify_hibernation_with_memory_workload(
        self, environment: Environment, log: Logger
    ) -> None:
        node = cast(RemoteNode, environment.nodes[0])
        is_distro_supported(node)
        stress_ng_tool = node.tools[StressNg]
        stress_ng_tool.launch(16, "100%", 300)
        verify_hibernation(node, log)
        stress_ng_tool.launch(16, "100%", 300)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        cleanup_env(environment)
