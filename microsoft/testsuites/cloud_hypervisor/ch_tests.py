# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path
from typing import Any

from assertpy.assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    node_requirement,
    schema,
    search_space,
)
from lisa.testsuite import TestResult
from lisa.tools import Lscpu, Modprobe
from lisa.util import SkippedException
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
    def before_suite(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        node.tools[Modprobe].load("openvswitch")

    def after_suite(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        node.tools[Modprobe].remove("openvswitch")

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        self._ensure_virtualization_enabled(node)

    @TestCaseMetadata(
        description="""
            Runs cloud-hypervisor integration tests.
        """,
        priority=3,
        requirement=node_requirement(
            node=schema.NodeSpace(
                core_count=search_space.IntRange(min=16),
                memory_mb=search_space.IntRange(min=16 * 1024),
            ),
        ),
    )
    def verify_cloud_hypervisor_integration_tests(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        log_path: Path,
        result: TestResult,
    ) -> None:
        failures = node.tools[CloudHypervisorTests].run_tests(
            result, environment, "integration"
        )
        assert_that(
            failures, f"Unexpected failures: {failures}"
        ).is_empty()

    @TestCaseMetadata(
        description="""
            Runs cloud-hypervisor live migration tests.
        """,
        priority=3,
        requirement=node_requirement(
            node=schema.NodeSpace(
                core_count=search_space.IntRange(min=16),
                memory_mb=search_space.IntRange(min=16 * 1024),
            ),
        ),
    )
    def verify_cloud_hypervisor_live_migration_tests(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        log_path: Path,
        result: TestResult,
    ) -> None:
        failures = node.tools[CloudHypervisorTests].run_tests(
            result, environment, "integration-live-migration"
        )
        assert_that(
            failures, f"Unexpected failures: {failures}"
        ).is_empty()

    def _ensure_virtualization_enabled(self, node: Node) -> None:
        virtualization_enabled = node.tools[Lscpu].is_virtualization_enabled()
        if not virtualization_enabled:
            raise SkippedException("Virtualization is not enabled in hardware")
