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
    This test suite validates the Windows action Run Command VM extension
    (Microsoft.CPlat.Core.RunCommandWindows), not Managed Run Command.
    """,
    tags=["VM_Extension", "RunCommandWindows"],
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        supported_os=[Windows],
    ),
)
class RunCommandWindowsTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.CPlat.Core"
    EXTENSION_TYPE = "RunCommandWindows"
    EXTENSION_KEY = "run_command_windows"

    @TestCaseMetadata(
        description="""
        Boot validation for the Windows action Run Command VM extension.

        Installs the explicitly requested candidate version with a harmless
        inline PowerShell script in the public settings 'script' array and
        no protected settings. Verifies provisioning succeeds, the installed
        version matches when a full candidate version is supplied, and the
        VM remains reachable, then removes the explicitly installed extension.
        No storage account, script download, or Run Command API call is required.

        The candidate version is read from 'extension_version' or
        'run_command_windows_version'.
        """,
        priority=5,
        tags=["microsoft.cplat.core.runcommandwindows"],
        maturity="preview",
    )
    def microsoft_cplat_core_runcommandwindows_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._boot_validation(
            node=node,
            log=log,
            variables=variables,
            settings={
                "script": [
                    "Write-Output 'Run Command Windows boot validation success'"
                ],
            },
        )
