# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import time
from typing import Any, cast

from assertpy import assert_that
from func_timeout import func_timeout
from microsoft.testsuites.power.common import (
    check_hibernation_disk_requirements,
    cleanup_env,
    is_distro_supported,
    run_network_workload,
    run_storage_workload,
    verify_hibernation,
)

from lisa import (
    Environment,
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.features import Disk, HibernationEnabled, Sriov, Synthetic
from lisa.features.availability import AvailabilityTypeNoRedundancy
from lisa.node import Node
from lisa.operating_system import BSD, Windows
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.testsuite import simple_requirement
from lisa.tools import Date, Hwclock, StressNg
from lisa.util import SkippedException
from lisa.util.perf_timer import create_timer


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

        check_hibernation_disk_requirements(node)

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
            supported_features=[HibernationEnabled(), AvailabilityTypeNoRedundancy()],
        ),
    )
    def verify_hibernation_synthetic_network(self, node: Node, log: Logger) -> None:
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
            supported_features=[HibernationEnabled(), AvailabilityTypeNoRedundancy()],
        ),
    )
    def verify_hibernation_sriov_network(self, node: Node, log: Logger) -> None:
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
            supported_features=[HibernationEnabled(), AvailabilityTypeNoRedundancy()],
        ),
    )
    def verify_hibernation_time_sync(self, node: Node, log: Logger) -> None:
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
            supported_features=[HibernationEnabled(), AvailabilityTypeNoRedundancy()],
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
            supported_features=[HibernationEnabled(), AvailabilityTypeNoRedundancy()],
        ),
    )
    def verify_hibernation_with_storage_workload(self, node: Node, log: Logger) -> None:
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
            supported_features=[HibernationEnabled(), AvailabilityTypeNoRedundancy()],
        ),
    )
    def verify_hibernation_with_memory_workload(self, node: Node, log: Logger) -> None:
        is_distro_supported(node)
        stress_ng_tool = node.tools[StressNg]
        stress_ng_tool.launch_vm_stressor(16, "90%", 300)
        verify_hibernation(node, log, throw_error=False)
        stress_ng_tool.launch_vm_stressor(16, "90%", 300)

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
            supported_features=[HibernationEnabled(), AvailabilityTypeNoRedundancy()],
        ),
    )
    def verify_hibernation_synthetic_network_max_nics(
        self, node: Node, log: Logger
    ) -> None:
        is_distro_supported(node)
        verify_hibernation(node, log)

    @TestCaseMetadata(
        description="""
            This case is to verify vm hibernation with sriov network with max nics.
            It has the same steps with verify_hibernation_synthetic_network_max_nics.
        """,
        priority=3,
        requirement=simple_requirement(
            min_nic_count=8,
            network_interface=Sriov(),
            supported_features=[HibernationEnabled(), AvailabilityTypeNoRedundancy()],
        ),
    )
    def verify_hibernation_sriov_network_max_nics(
        self, node: Node, log: Logger
    ) -> None:
        is_distro_supported(node)
        verify_hibernation(node, log)

    @TestCaseMetadata(
        description="""
            This case is to verify vm hibernation with max data disks.
            It has the same steps with verify_hibernation_synthetic_network_max_nics.
        """,
        priority=3,
        requirement=simple_requirement(
            min_nic_count=8,
            supported_features=[HibernationEnabled(), AvailabilityTypeNoRedundancy()],
            min_data_disk_count=32,
        ),
    )
    def verify_hibernation_max_data_disks(self, node: Node, log: Logger) -> None:
        is_distro_supported(node)
        disk = node.features[Disk]
        data_disks_before_hibernation = disk.get_raw_data_disks()
        verify_hibernation(node, log)
        data_disks_after_hibernation = disk.get_raw_data_disks()
        assert_that(data_disks_before_hibernation).described_as(
            "data disks are inconsistent after hibernation"
        ).is_length(len(data_disks_after_hibernation))

    @TestCaseMetadata(
        description="""
            This case is to verify vm hibernation using LinuxHibernateExtension.

            Steps,
            1. Install LinuxHibernateExtension to prepare prerequisite for vm
             hibernation.
            2. Get nics info before hibernation.
            3. Hibernate vm using Stop-Hibernate.
            4. Check vm is inaccessible (deallocated status).
            5. Resume vm by starting vm.
            6. Check vm hibernation successfully by verifying boot time consistency.
            7. Get nics info after hibernation.
            8. Fail the case if nics count and info changes after vm resume.
            9. Uninstall the extension.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[
                HibernationEnabled(),
                AvailabilityTypeNoRedundancy(),
                AzureExtension,
            ],
        ),
    )
    def verify_hibernation_with_vm_extension(self, node: Node, log: Logger) -> None:
        is_distro_supported(node)
        verify_hibernation(
            node, log, use_hibernation_setup_tool=False, verify_using_logs=False
        )

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")

        # Add timeout for cleanup environment operation (5 minutes)
        cleanup_timeout = 300
        timer = create_timer()

        try:
            func_timeout(timeout=cleanup_timeout, func=cleanup_env, args=(environment,))
        except Exception as cleanup_ex:
            elapsed_time = timer.elapsed()
            log.info(
                f"Environment cleanup failed after {elapsed_time:.2f} seconds: "
                f"{cleanup_ex}"
            )
            # Mark all nodes as dirty since cleanup failed
            for node in environment.nodes.list():
                if isinstance(node, RemoteNode):
                    node.mark_dirty()
