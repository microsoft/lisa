# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path
from typing import Any, Dict

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
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        if not isinstance(node.os, (CBLMariner, Ubuntu)):
            raise SkippedException(
                f"Cloud Hypervisor tests are not implemented in LISA for {node.os.name}"
            )
        node.tools[Modprobe].load("openvswitch")
        self._ensure_virtualization_enabled(node)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        node.tools[Modprobe].remove(["openvswitch"])

    @TestCaseMetadata(
        description="""
            Runs cloud-hypervisor integration tests.
        """,
        priority=3,
        timeout=CloudHypervisorTests.CASE_TIME_OUT,
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
        variables: Dict[str, Any],
    ) -> None:
        hypervisor = self._get_hypervisor_param(node)
        ref = variables.get("cloudhypervisor_ref", "")
        # below variable expects a comma separated list of full testnames
        include_list, exclude_list = get_test_list(
            variables, "ch_integration_tests_included", "ch_integration_tests_excluded"
        )
        node.tools[CloudHypervisorTests].run_tests(
            result,
            environment,
            "integration",
            hypervisor,
            log_path,
            ref,
            include_list,
            exclude_list,
        )

    @TestCaseMetadata(
        description="""
            Runs cloud-hypervisor live migration tests.
        """,
        priority=3,
        timeout=CloudHypervisorTests.CASE_TIME_OUT,
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
        variables: Dict[str, Any],
    ) -> None:
        hypervisor = self._get_hypervisor_param(node)
        ref = variables.get("cloudhypervisor_ref", "")
        # below variable expects a comma separated list of full testnames
        include_list, exclude_list = get_test_list(
            variables,
            "ch_live_migration_tests_included",
            "ch_live_migration_tests_excluded",
        )
        node.tools[CloudHypervisorTests].run_tests(
            result,
            environment,
            "integration-live-migration",
            hypervisor,
            log_path,
            ref,
            include_list,
            exclude_list,
        )

    @TestCaseMetadata(
        description="""
            Runs cloud-hypervisor performance metrics tests.
        """,
        priority=3,
        timeout=CloudHypervisorTests.CASE_TIME_OUT,
    )
    def verify_cloud_hypervisor_performance_metrics_tests(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        log_path: Path,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        hypervisor = self._get_hypervisor_param(node)
        ref = variables.get("cloudhypervisor_ref", "")
        # below variable expects a comma separated list of full testnames
        include_list, exclude_list = get_test_list(
            variables,
            "ch_perf_tests_included",
            "ch_perf_tests_excluded",
        )
        subtest_timeout = variables.get("ch_perf_subtest_timeout", None)
        node.tools[CloudHypervisorTests].run_metrics_tests(
            result,
            environment,
            hypervisor,
            log_path,
            ref,
            include_list,
            exclude_list,
            subtest_timeout,
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
        kvm_exists = node.tools[Ls].path_exists(path="/dev/kvm", sudo=True)
        if kvm_exists:
            return "kvm"
        mshv_exists = node.tools[Ls].path_exists(path="/dev/mshv", sudo=True)
        if mshv_exists:
            return "mshv"
        return ""


def get_test_list(variables: Dict[str, Any], var1: str, var2: str) -> Any:
    tests_raw = variables.get(var1, "")
    test_list1 = tests_raw.split(",") if tests_raw else None
    tests_raw = variables.get(var2, "")
    test_list2 = tests_raw.split(",") if tests_raw else None
    return test_list1, test_list2
