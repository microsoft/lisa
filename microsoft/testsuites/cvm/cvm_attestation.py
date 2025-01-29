# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import base64
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
from lisa.features.security_profile import CvmEnabled
from lisa.operating_system import CBLMariner, Ubuntu
from lisa.sut_orchestrator import AZURE, CLOUD_HYPERVISOR
from lisa.sut_orchestrator.libvirt.context import NodeContext
from lisa.testsuite import TestResult, simple_requirement
from lisa.tools import Ls, Lscpu
from lisa.tools.lscpu import CpuType
from lisa.util import SkippedException, UnsupportedDistroException
from microsoft.testsuites.cvm.cvm_attestation_tool import (
    AzureCVMAttestationTests,
    NestedCVMAttestationTests,
    SnpGuest,
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
        if not isinstance(node.os, Ubuntu) and not isinstance(node.os, CBLMariner):
            raise SkippedException(
                UnsupportedDistroException(
                    node.os,
                    "CVM attestation report supports only Ubuntu and Azure Linux.",
                )
            )

        if node.tools[Lscpu].get_cpu_type() != CpuType.AMD:
            raise SkippedException(
                "CVM attestation report supports only SEV-SNP (AMD) CPU."
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
        if isinstance(node.os, Ubuntu):
            node.tools[AzureCVMAttestationTests].run_cvm_attestation(
                result,
                environment,
                log_path,
            )
        elif isinstance(node.os, CBLMariner):
            node.tools[SnpGuest].run_cvm_attestation()


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

        if node.tools[Lscpu].get_cpu_type() != CpuType.AMD:
            raise SkippedException(
                "CVM attestation report supports only SEV-SNP (AMD) CPU."
            )

    @TestCaseMetadata(
        description="""
            Runs get-snp-report tool to generate
            and verify attestation report for nested cvm.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[CvmEnabled()],
            supported_platform_type=[CLOUD_HYPERVISOR],
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
        from lisa.sut_orchestrator.libvirt.context import get_node_context

        node_context = get_node_context(node)
        host_data = self._get_host_data(node_context)
        if not host_data:
            raise SkippedException("host_data is empty")
        node.tools[NestedCVMAttestationTests].run_cvm_attestation(
            result,
            environment,
            log_path,
            host_data,
        )

    def _get_host_data(self, node_context: NodeContext) -> str:
        # Based on libvirt version our libvirt platform will set
        # either plain text or b64 encoded string as host data.
        # We need to decode it as this test would get host_data
        # from attestation tool as plain text
        # or
        # Return original data if not set as base64 encoded string
        host_data = node_context.host_data
        if node_context.is_host_data_base64:
            host_data = base64.b64decode(host_data).hex()
        return host_data
