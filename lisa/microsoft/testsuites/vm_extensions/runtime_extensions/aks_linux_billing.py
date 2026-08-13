# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict

from microsoft.testsuites.vm_extensions.vm_extension_base import VmExtensionTestBase

from lisa import Logger, Node, TestCaseMetadata, TestSuiteMetadata, simple_requirement
from lisa.operating_system import BSD, Windows
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.features import AzureExtension


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    This test suite validates the Microsoft AKS Linux Billing VM extension.
    """,
    tags=["VM_Extension", "Microsoft.AKS.Compute.AKS.Linux.Billing"],
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        unsupported_os=[BSD, Windows],
    ),
)
class AksLinuxBillingTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.AKS"
    EXTENSION_TYPE = "Compute.AKS.Linux.Billing"
    EXTENSION_KEY = "aks_linux_billing"

    @TestCaseMetadata(
        description="""
        Basic boot validation for the Microsoft AKS Linux Billing VM extension.

        Installs the explicitly requested candidate version with empty public
        settings and no protected settings. Verifies that extension provisioning
        succeeds, the installed patch version matches when a full version is
        supplied, and the VM remains reachable before removing the extension.

        The candidate version is read from the 'extension_version' or
        'aks_linux_billing_version' runbook variable.
        """,
        priority=5,
        maturity="preview",
    )
    def microsoft_aks_compute_aks_linux_billing_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._boot_validation(
            node=node,
            log=log,
            variables=variables,
            settings={},
        )
