# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path

from assertpy.assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    node_requirement,
    schema,
    search_space,
)
from lisa.tools import Lscpu
from lisa.utils import SkippedException
from microsoft.testsuites.cloud_hypervisor.ch_tests_tool import CloudHypervisorTests


@TestSuiteMetadata(
    area="cloud-hypervisor",
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
        requirement=node_requirement(
            node=schema.NodeSpace(
                core_count=16, memory_mb=search_space.IntRange(min=16 * 1024)
            ),
        ),
    )
    def verify_cloud_hypervisor_integration_tests(
        self, log: Logger, node: Node, log_path: Path
    ) -> None:
        self._ensure_virtualization_enabled()
        skip_tests = ["test_vfio"]
        failures = node.tools[CloudHypervisorTests].run_tests("integration", skip_tests)
        assert_that(failures).is_empty()

    @TestCaseMetadata(
        description="""
            Runs cloud-hypervisor live migration tests.
        """,
        priority=3,
        requirement=node_requirement(
            node=schema.NodeSpace(
                core_count=16, memory_mb=search_space.IntRange(min=16 * 1024)
            ),
        ),
    )
    def verify_cloud_hypervisor_live_migration_tests(
        self, log: Logger, node: Node, log_path: Path
    ) -> None:
        self._ensure_virtualization_enabled()
        failures = node.tools[CloudHypervisorTests].run_tests(
            "integration-live-migration"
        )
        assert_that(failures).is_empty()

    def _ensure_virtualization_support(self) -> None:
        virtualization_enabled = self.node.tools[Lscpu].is_virtualization_enabled()
        if not virtualization_enabled:
            raise SkippedException("Virtualization is not enabled in hardware")
