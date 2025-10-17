# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path
from typing import Any

from microsoft.testsuites.kvm.kvm_unit_tests_tool import KvmUnitTests

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import BSD, CBLMariner, Ubuntu, Windows
from lisa.testsuite import TestResult
from lisa.tools import Lscpu
from lisa.util import SkippedException


@TestSuiteMetadata(
    area="kvm",
    category="community",
    description="""
    This test suite is for executing the community maintained KVM tests.
    See: https://gitlab.com/kvm-unit-tests/kvm-unit-tests
    """,
)
class KvmUnitTestSuite(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        if isinstance(node.os, BSD) or isinstance(node.os, Windows):
            raise SkippedException(f"{node.os} is not supported.")

    @TestCaseMetadata(
        description="""
            Runs kvm-unit-tests.
        """,
        priority=3,
    )
    def verify_kvm_unit_tests(
        self,
        node: Node,
        log_path: Path,
        result: TestResult,
    ) -> None:
        # ensure virtualization is enabled in hardware before running tests
        virtualization_enabled = node.tools[Lscpu].is_virtualization_enabled()
        if not virtualization_enabled:
            raise SkippedException("Virtualization is not enabled in hardware")
        if not isinstance(node.os, (CBLMariner, Ubuntu)):
            raise SkippedException(
                f"KVM unit tests are not implemented in LISA for {node.os.name}"
            )

        node.tools[KvmUnitTests].run_tests(result, log_path)
