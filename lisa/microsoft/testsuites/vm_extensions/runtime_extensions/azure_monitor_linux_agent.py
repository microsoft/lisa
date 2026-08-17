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
    This test suite validates the Azure Monitor Agent Linux VM extension
    (Microsoft.Azure.Monitor.AzureMonitorLinuxAgent).

    Coverage starts with boot validation: install the extension with empty
    settings, confirm provisioning succeeds, confirm the requested version was
    installed, confirm the VM is still reachable over SSH, then remove the
    extension.
    """,
    tags=["VM_Extension", "AzureMonitorLinuxAgent"],
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        unsupported_os=[BSD],
    ),
)
class AzureMonitorLinuxAgentTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.Azure.Monitor"
    EXTENSION_TYPE = "AzureMonitorLinuxAgent"
    EXTENSION_KEY = "azure_monitor_linux_agent"

    @TestCaseMetadata(
        description="""
        Basic boot validation for the Azure Monitor Agent Linux VM extension.

        Installs the explicitly requested candidate version with empty public
        settings and no protected settings. Verifies that extension provisioning
        succeeds, the installed patch version matches when a full version is
        supplied, and the VM remains reachable before removing the extension.

        The candidate version is read from the 'extension_version' or
        'azure_monitor_linux_agent_version' runbook variable.
        """,
        priority=5,
        maturity="preview",
    )
    def microsoft_azure_monitor_azuremonitorlinuxagent_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._boot_validation(
            node=node,
            log=log,
            variables=variables,
            settings={},
        )
