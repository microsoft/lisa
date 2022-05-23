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
    simple_requirement,
)
from lisa.sut_orchestrator import AZURE, READY
from microsoft.testsuites.kvm.kvm_unit_tests_tool import KvmUnitTests


@TestSuiteMetadata(
    area="kvm",
    category="community",
    description="""
    This test suite is for executing the community maintained KVM tests.
    See: https://gitlab.com/kvm-unit-tests/kvm-unit-tests
    """,
)
class KvmUnitTestSuite(TestSuite):
    @TestCaseMetadata(
        description="""
            Runs kvm-unit-tests.
        """,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
        priority=3,
    )
    def verify_kvm_unit_tests_for_azure_vm(
        self, log: Logger, node: Node, log_path: Path
    ) -> None:
        # TODO: These failures need to be investigated to figure out the exact
        # cause.
        expected_failures = [
            "pmu_lbr",
            "svm_pause_filter",
            "vmx",
            "ept",
            "debug",
        ]

        failures = node.tools[KvmUnitTests].run_tests(log_path)
        if failures:
            log.info(f"Failed tests: {failures}")

        unexpected_failures = list(
            filter(lambda x: x not in expected_failures, failures)
        )

        assert_that(unexpected_failures).is_empty()
