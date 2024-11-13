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
    features,
)
from lisa.features.security_profile import CvmEnabled
from lisa.operating_system import Ubuntu
from lisa.sut_orchestrator import AZURE
from lisa.testsuite import TestResult, simple_requirement
from lisa.tools import Ls
from lisa.util import SkippedException, UnsupportedDistroException
from microsoft.testsuites.cvm.cvm_attestation_tool import (
    AzureCVMAttestationTests,
    NestedCVMAttestationTests,
)


@TestSuiteMetadata(
    area="cvm",
    category="functional",
    description="""
    This test suite is for generating CVM attestation report only for azure cvms.
    """,
)
class AzureCVMAttestationTestSuite(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        if not isinstance(node.os, Ubuntu):
            raise SkippedException(
                UnsupportedDistroException(
                    node.os, "CVM attestation report supports only Ubuntu."
                )
            )

    @TestCaseMetadata(
        description="""
            Runs get-snp-report tool to generate
            and create attestation report for azure cvm.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[CvmEnabled()],
            supported_platform_type=[AZURE],
        ),
    )
    def verify_azure_cvm_attestation_report(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        log_path: Path,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        node.tools[AzureCVMAttestationTests].run_cvm_attestation(
            result,
            environment,
            log_path,
        )


@TestSuiteMetadata(
    area="cvm",
    category="functional",
    description="""
    This test suite is for generating and verifying
    CVM attestation report only for nested cvms.
    """,
)
class NestedCVMAttestationTestSuite(TestSuite):
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
        requirement=simple_requirement(
            supported_features=[features.CVMNestedVirtualization],
        ),
    )
    def verify_nested_cvm_attestation_report(
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
        node.tools[NestedCVMAttestationTests].run_cvm_attestation(
            result,
            environment,
            log_path,
            host_data,
        )
