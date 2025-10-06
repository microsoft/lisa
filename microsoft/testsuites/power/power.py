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
from lisa.features.availability import AvailabilityTypeNoRedundancy
from lisa.node import Node
from lisa.operating_system import BSD, Windows
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.testsuite import simple_requirement
from lisa.tools import Cat, Date, Hwclock, Ls, StressNg
from lisa.util import LisaException, SkippedException
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
        priority=3,
        requirement=simple_requirement(
            supported_features=[HibernationEnabled(), AvailabilityTypeNoRedundancy()],
        ),
    )
    def verify_hibernation_using_extension(self, node: Node, log: Logger) -> None:
        is_distro_supported(node)

        # Get Azure extension feature
        azure_extension = node.features[AzureExtension]
        extension_name = "LinuxHibernateExtension"

        try:
            # Install LinuxHibernateExtension
            log.info("Installing LinuxHibernateExtension...")
            extension_result = azure_extension.create_or_update(
                type_="LinuxHibernateExtension",
                name=extension_name,
                publisher="Microsoft.CPlat.Core",
                type_handler_version="1.0",
                auto_upgrade_minor_version=True,
                timeout=60 * 15,  # 15 minutes timeout
            )

            log.debug(f"Extension installation result: {extension_result}")

            # Verify the extension installation was successful
            if extension_result is None or "provisioning_state" not in extension_result:
                raise LisaException(
                    "Hibernation Extension result should not be None and"
                    " should contain 'provisioning_state' key"
                )

            provisioning_state = extension_result["provisioning_state"]
            assert_that(provisioning_state).described_as(
                "Expected the extension to succeed"
            ).is_equal_to("Succeeded")

            verify_hibernation(
                node, log, use_hibernation_setup_tool=False, verify_using_logs=False
            )
            try:
                azure_extension.delete(name=extension_name, ignore_not_found=True)
                log.info("Extension uninstalled successfully")
            except Exception as cleanup_ex:
                log.info(
                    f"Failed to uninstall extension after successful test: {cleanup_ex}"
                )
                node.mark_dirty()

        except Exception as test_ex:
            # Test failed - collect extension logs for debugging
            log.error(f"Hibernation extension test failed: {test_ex}")
            self._collect_hibernation_extension_logs(node, log)
            log.info("Marking node as dirty due to hibernation extension test failure")
            node.mark_dirty()
            raise

    def _collect_hibernation_extension_logs(self, node: Node, log: Logger) -> None:
        """Collect and print LinuxHibernateExtension logs for debugging"""
        try:
            extension_log_dir = (
                "/var/log/azure/Microsoft.CPlat.Core.LinuxHibernateExtension"
            )
            extension_log_path = node.get_pure_path(extension_log_dir)

            # Check if the log directory exists
            if not node.shell.exists(extension_log_path):
                log.info(f"Extension log directory {extension_log_path} does not exist")
                return
            ls = node.tools[Ls]
            cat = node.tools[Cat]

            try:
                log_files = ls.list_dir(extension_log_dir, sudo=True)
                log_files.sort()
            except Exception as ls_ex:
                log.debug(f"Failed to list extension log files: {ls_ex}")
                return

            if not log_files:
                log.info("No extension log files found")
                return

            log.debug(
                f"Found {len(log_files)} extension log files: {', '.join(log_files)}"
            )

            # Print contents of each log file
            for log_file in log_files:
                if not log_file.strip():
                    continue

                log_file_path = f"{extension_log_dir}/{log_file.strip()}"

                # Check if it's a directory and skip it
                if node.shell.is_dir(node.get_pure_path(log_file_path)):
                    log.debug(f"Skipping {log_file} (directory)")
                    continue

                log.info(f"=== Contents of {log_file} ===")

                try:
                    content = cat.read(log_file_path, sudo=True)
                    log.info(f"{log_file} content:\n{content}")
                except Exception as cat_ex:
                    log.debug(f"Failed to read {log_file}: {cat_ex}")

                log.info(f"=== End of {log_file} ===")

        except Exception as log_ex:
            log.info(f"Failed to collect extension logs: {log_ex}")

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        cleanup_env(environment)
