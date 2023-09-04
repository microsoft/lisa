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
)
from lisa.testsuite import TestResult
from lisa.tools import Ls
from lisa.util import SkippedException
from microsoft.testsuites.cvm.cvm_attestation_tool import CVMAttestationTests


@TestSuiteMetadata(
    area="cvm",
    category="functional",
    description="""
    This test suite is for generating and verifying CVM attestation report.
    """,
)
class CVMAttestationTestSuite(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        sev_guest_exists = node.tools[Ls].path_exists(
            path="/dev/sev-guest",
            sudo=True,
        )
        if not sev_guest_exists:
            raise SkippedException("/dev/sev-guest: Device Not Found")

    @TestCaseMetadata(
        description="""
            Runs get-snp-report tool to generate
            and verify attestation report for nested cvm.
        """,
        priority=3,
    )
    def verify_cvm_attestation_report(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        log_path: Path,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        host_data = variables.get("host_data", "")
        if not host_data:
            raise SkippedException("host_data is empty")
        node.tools[CVMAttestationTests].run_cvm_attestation(
            result,
            environment,
            log_path,
            host_data,
        )
