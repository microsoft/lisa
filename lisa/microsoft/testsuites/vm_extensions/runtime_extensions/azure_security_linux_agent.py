# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict

from microsoft.testsuites.vm_extensions.vm_extension_base import VmExtensionTestBase

from lisa import Logger, Node, TestCaseMetadata, TestSuiteMetadata, simple_requirement
from lisa.operating_system import BSD
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.features import AzureExtension


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    This test suite validates the Azure Security Linux Agent VM extension
    (Microsoft.Azure.Security.Monitoring.AzureSecurityLinuxAgent).

    The Azure Security Linux Agent provides security logging and monitoring
    coverage for Linux VMs (Microsoft Defender for Cloud / Azure Security
    Center). It is the mandatory boot validation coverage required for the
    publisher to onboard to Functional Validation.
    """,
    tags=["VM_Extension", "AzureSecurityLinuxAgent"],
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        unsupported_os=[BSD],
    ),
)
class AzureSecurityLinuxAgentTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.Azure.Security.Monitoring"
    EXTENSION_TYPE = "AzureSecurityLinuxAgent"
    EXTENSION_KEY = "azure_security_linux_agent"

    @TestCaseMetadata(
        description="""
        Basic boot validation for the Azure Security Linux Agent VM extension.

        Installs the extension with empty inline settings (the agent requires
        no storage account or public blob access), verifies that provisioning
        succeeds and the requested version is delivered, confirms the VM is
        still reachable, then removes the extension.

        The extension version is read from runbook variable
        'azure_security_linux_agent_version' (or the generic
        'extension_version'); the case is skipped when neither is set. The
        deployed extension is named
        '<publisher>_<extension_type>_boot_validation_test'.
        """,
        priority=1,
        maturity="experimental",
        requirement=simple_requirement(
            supported_features=[AzureExtension],
            supported_platform_type=[AZURE],
            unsupported_os=[BSD],
        ),
    )
    def microsoft_azure_security_monitoring_azuresecuritylinuxagent_boot_validation_test(  # noqa: E501
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        # The Azure Security Linux Agent installs without inline settings.
        self._boot_validation(node, log, variables, settings={})
