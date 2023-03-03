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
from lisa.features import Disk, HibernationEnabled, Sriov, Synthetic
from lisa.node import Node
from lisa.operating_system import BSD, Windows
from lisa.testsuite import simple_requirement
from lisa.tools import Date, Hwclock, StressNg
from lisa.util import SkippedException
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
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        if isinstance(node.os, BSD) or isinstance(node.os, Windows):
            raise SkippedException(f"{node.os} is not supported.")

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
        verify_hibernation(environment, log)

    @TestCaseMetadata(
        description="""
            This case is to verify vm hibernation with synthetic network with max nics.

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
            min_nic_count=8,
            network_interface=Synthetic(),
            supported_features=[HibernationEnabled()],
        ),
    )
    def verify_hibernation_synthetic_network_max_nics(
        self, environment: Environment, log: Logger
    ) -> None:
        node = cast(RemoteNode, environment.nodes[0])
        is_distro_supported(node)
        verify_hibernation(environment, log)

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
        verify_hibernation(environment, log)

    @TestCaseMetadata(
        description="""
            This case is to verify vm hibernation with sriov network with max nics.
            It has the same steps with verify_hibernation_synthetic_network_max_nics.
        """,
        priority=3,
        requirement=simple_requirement(
            min_nic_count=8,
            network_interface=Sriov(),
            supported_features=[HibernationEnabled()],
        ),
    )
    def verify_hibernation_sriov_network_max_nics(
        self, environment: Environment, log: Logger
    ) -> None:
        node = cast(RemoteNode, environment.nodes[0])
        is_distro_supported(node)
        verify_hibernation(environment, log)

    @TestCaseMetadata(
        description="""
            This case is to verify vm hibernation with max data disks.
            It has the same steps with verify_hibernation_synthetic_network_max_nics.
        """,
        priority=3,
        requirement=simple_requirement(
            min_nic_count=8,
            supported_features=[HibernationEnabled()],
            min_data_disk_count=32,
        ),
    )
    def verify_hibernation_max_data_disks(
        self, environment: Environment, log: Logger
    ) -> None:
        node = cast(RemoteNode, environment.nodes[0])
        is_distro_supported(node)
        disk = node.features[Disk]
        data_disks_before_hibernation = disk.get_raw_data_disks()
        verify_hibernation(environment, log)
        data_disks_after_hibernation = disk.get_raw_data_disks()
        assert_that(
            len(data_disks_before_hibernation),
            "data disks are inconsistent after hibernation",
        ).is_equal_to(len(data_disks_after_hibernation))

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

        hwclock = node.tools[Hwclock]
        hwclock.run(
            "--set --date $(date -d 'next year' +%Y-%m-%d)",
            force_run=True,
            shell=True,
            sudo=True,
        )

        changed_date_before_hb = hwclock.get()
        assert_that(
            changed_date_before_hb.year - current_date.year,
            "fail to reset time",
        ).is_equal_to(1)
        verify_hibernation(environment, log)
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
        verify_hibernation(environment, log)
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
        verify_hibernation(environment, log)
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
        stress_ng_tool.launch_vm_stressor(16, "90%", 300)
        verify_hibernation(environment, log, ignore_call_trace=True)
        stress_ng_tool.launch_vm_stressor(16, "90%", 300)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        cleanup_env(environment)
