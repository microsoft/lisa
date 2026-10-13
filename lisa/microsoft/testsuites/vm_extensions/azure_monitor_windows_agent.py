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
    This test suite validates the Azure Monitor Agent Windows VM extension
    (Microsoft.Azure.Monitor.AzureMonitorWindowsAgent).
    """,
    tags=["VM_Extension"],
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        supported_os=[Windows],
    ),
)
class AzureMonitorWindowsAgentTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.Azure.Monitor"
    EXTENSION_TYPE = "AzureMonitorWindowsAgent"
    EXTENSION_KEY = "azure_monitor_windows_agent"

    @TestCaseMetadata(
        description="""
        Basic boot validation for the Azure Monitor Agent Windows VM extension.

        Installs the explicitly requested candidate version with empty public
        settings and no protected settings. Verifies that extension provisioning
        succeeds, the installed patch version matches when a full version is
        supplied, and the VM remains reachable before removing the extension.

        The candidate version is read from the 'extension_version' or
        'azure_monitor_windows_agent_version' runbook variable.
        """,
        priority=5,
        tags=["microsoft.azure.monitor.azuremonitorwindowsagent"],
        maturity="preview",
    )
    def microsoft_azure_monitor_azuremonitorwindowsagent_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._boot_validation(
            node=node,
            log=log,
            variables=variables,
            settings={},
        )
