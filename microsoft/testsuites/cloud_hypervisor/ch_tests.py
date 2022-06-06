# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path

from assertpy.assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from microsoft.testsuites.cloud_hypervisor.ch_tests_tool import CloudHypervisorTests 


@TestSuiteMetadata(
    area="kvm",
    category="community",
    description="""
    This test suite is for executing the tests maintained in the
    upstream cloud-hypervisor repo.
    """,
)
class CloudHypervisorTestSuite(TestSuite):
    @TestCaseMetadata(
        description="""
            Runs cloud-hypervisor integration tests.
        """,
        priority=3,
    )
    def verify_cloud_hypervisor_integration_tests(
        self,
        log: Logger,
        node: Node,
        log_path: Path
    ) -> None:
        excluded_tests = [ "test_vfio" ]
        failures = node.tools[CloudHypervisorTests].run_tests(
            "integration",
            excluded_tests
        )
        assert_that(failures).is_empty()

    @TestCaseMetadata(
        description="""
            Runs cloud-hypervisor live migration tests.
        """,
        priority=3,
    )
    def verify_cloud_hypervisor_live_migration_tests(
        self,
        log: Logger,
        node: Node,
        log_path: Path
    ) -> None:
        failures = node.tools[CloudHypervisorTests].run_tests(
            "integration-live-migration"
        )
        assert_that(failures).is_empty()
