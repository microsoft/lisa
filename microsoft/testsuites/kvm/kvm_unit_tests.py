# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.testsuite import TestResult
from lisa.tools import Lscpu
from lisa.util import SkippedException
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
        priority=3,
    )
    def verify_kvm_unit_tests(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        log_path: Path,
        result: TestResult,
    ) -> None:
        # ensure virtualization is enabled in hardware before running tests
        virtualization_enabled = node.tools[Lscpu].is_virtualization_enabled()
        if not virtualization_enabled:
            raise SkippedException("Virtualization is not enabled in hardware")

        node.tools[KvmUnitTests].run_tests(result, environment, log_path)
