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
    This test suite validates the Microsoft AKS Linux AKSNode VM extension.
    """,
    tags=["VM_Extension"],
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        unsupported_os=[BSD, Windows],
    ),
)
class AksLinuxAksNodeTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.AKS"
    EXTENSION_TYPE = "Compute.AKS.Linux.AKSNode"
    EXTENSION_KEY = "aks_linux_aksnode"

    @TestCaseMetadata(
        description="""
        Basic boot validation for the Microsoft AKS Linux AKSNode VM extension.

        Installs the explicitly requested candidate version with empty public
        settings and no protected settings. Verifies that extension provisioning
        succeeds, the installed patch version matches when a full version is
        supplied, and the VM remains reachable before removing the extension.

        This Phase 1 case validates the package and handler lifecycle on a Linux
        VM. AKS node functionality requires a separate AKS-compatible environment.

        The candidate version is read from the 'extension_version' or
        'aks_linux_aksnode_version' runbook variable.
        """,
        priority=5,
        tags=["microsoft.aks.compute.aks.linux.aksnode"],
        maturity="preview",
    )
    def microsoft_aks_compute_aks_linux_aksnode_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._boot_validation(
            node=node,
            log=log,
            variables=variables,
            settings={},
        )
