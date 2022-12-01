# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path
from typing import Any

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
from lisa.operating_system import CBLMariner, Ubuntu
from lisa.testsuite import TestResult
from lisa.tools import Ls, Lscpu, Modprobe, Usermod
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
        if not isinstance(node.os, (CBLMariner, Ubuntu)):
            raise SkippedException(
                f"Cloud Hypervisor tests are not implemented in LISA for {node.os.name}"
            )
        self._ensure_virtualization_enabled(node)

    @TestCaseMetadata(
        description="""
            Runs cloud-hypervisor integration tests.
        """,
        priority=3,
        timeout=CloudHypervisorTests.TIME_OUT,
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
        hypervisor = self._get_hypervisor_param(node)
        node.tools[CloudHypervisorTests].run_tests(
            result, environment, "integration", hypervisor
        )

    @TestCaseMetadata(
        description="""
            Runs cloud-hypervisor live migration tests.
        """,
        priority=3,
        timeout=CloudHypervisorTests.TIME_OUT,
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
        hypervisor = self._get_hypervisor_param(node)
        node.tools[CloudHypervisorTests].run_tests(
            result, environment, "integration-live-migration", hypervisor
        )

    @TestCaseMetadata(
        description="""
            Runs cloud-hypervisor performance metrics tests.
        """,
        priority=3,
        timeout=CloudHypervisorTests.TIME_OUT,
    )
    def verify_cloud_hypervisor_performance_metrics_tests(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        log_path: Path,
        result: TestResult,
    ) -> None:
        hypervisor = self._get_hypervisor_param(node)
        node.tools[CloudHypervisorTests].run_metrics_tests(
            result, environment, hypervisor, log_path
        )

    def _ensure_virtualization_enabled(self, node: Node) -> None:
        virtualization_enabled = node.tools[Lscpu].is_virtualization_enabled()
        mshv_exists = node.tools[Ls].path_exists(path="/dev/mshv", sudo=True)
        if not virtualization_enabled and not mshv_exists:
            raise SkippedException("Virtualization is not enabled in hardware")
        # add user to mshv group for access to /dev/mshv
        if mshv_exists:
            node.tools[Usermod].add_user_to_group("mshv", sudo=True)

    def _get_hypervisor_param(self, node: Node) -> str:
        mshv_exists = node.tools[Ls].path_exists(path="/dev/mshv", sudo=True)
        if mshv_exists:
            return "mshv"
        return "kvm"
