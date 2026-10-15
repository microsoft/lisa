# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict

from microsoft.testsuites.vm_extensions.vm_extension_base import VmExtensionTestBase

from lisa import Logger, Node, TestCaseMetadata, TestSuiteMetadata, simple_requirement
from lisa.operating_system import Windows
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.features import AzureExtension


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    This test suite validates the Windows Custom Script VM extension
    (Microsoft.Compute.CustomScriptExtension).
    """,
    tags=["VM_Extension", "CustomScriptExtension"],
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        supported_os=[Windows],
    ),
)
class CustomScriptWindowsTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.Compute"
    EXTENSION_TYPE = "CustomScriptExtension"
    EXTENSION_KEY = "custom_script_windows"

    @TestCaseMetadata(
        description="""
        Boot validation for the Windows Custom Script VM extension.

        Installs the explicitly requested candidate version with a harmless
        inline PowerShell command and no file URIs or protected settings.
        Verifies provisioning succeeds, the installed version matches when a
        full candidate version is supplied, and the VM remains reachable,
        then removes the extension. No storage account or script download
        is required.

        The candidate version is read from 'extension_version' or
        'custom_script_windows_version'.
        """,
        priority=5,
        tags=["microsoft.compute.customscriptextension"],
        maturity="preview",
    )
    def microsoft_compute_customscriptextension_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._boot_validation(
            node=node,
            log=log,
            variables=variables,
            settings={
                "commandToExecute": (
                    "powershell.exe -NoProfile -NonInteractive -Command "
                    "\"Write-Output 'CSE Windows boot validation success'\""
                ),
            },
        )
