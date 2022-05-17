# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa import (
    Logger,
    Node,
    RemoteNode,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
)

from assertpy.assertpy import assert_that
from pathlib import Path
from lisa.tools import KvmUnitTests
from lisa.util import constants

@TestSuiteMetadata(
    area="storage",
    category="community",
    description="""
    This test suite is to execute tests from the community kvm-unit-tests repo.
    """,
)
class KvmUnitTestSuite(TestSuite):
    # These tests take some time to finish executing. The default
    # timeout of 600 is not sufficient.
    TIME_OUT = 1200

    @TestCaseMetadata(
        description="""
            Runs the kvm-unit-tests suite for Azure VMs.
        """,
        priority=3,
        timeout=TIME_OUT,
    )
    def kvm_unit_tests_for_azure_vm(
        self, log: Logger, node: Node, log_path: Path
    ) -> None:
        expected_failures = [
            'pmu_lbr',
            'svm_pause_filter',
            'vmx',
            'ept',
            'debug',
        ]

        failures = node.tools[KvmUnitTests].run_tests(self.TIME_OUT)
        if failures:
            log.info(f"Failed tests: {failures}")

        node.tools[KvmUnitTests].save_logs(failures, log_path)

        unexpected_failures = list(
            filter(lambda x: x not in expected_failures, failures)
        )

        assert_that(unexpected_failures).is_empty()
