# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict

from microsoft.testsuites.vm_extensions.vm_extension_base import VmExtensionTestBase

from lisa import Logger, Node, TestCaseMetadata, TestSuiteMetadata, simple_requirement
from lisa.environment import Environment
from lisa.operating_system import BSD, Windows
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    add_system_assign_identity,
    get_node_context,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    This test suite validates the Microsoft Entra ID SSH login VM extension
    (Microsoft.Azure.ActiveDirectory.AADSSHLoginForLinux).

    Coverage starts with boot validation: enable a system-assigned managed
    identity, install the extension with empty settings, confirm provisioning
    succeeds, confirm the requested version was installed, confirm the VM is
    still reachable over SSH, then remove the extension.
    """,
    tags=["VM_Extension", "AADSSHLoginForLinux"],
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        unsupported_os=[BSD, Windows],
    ),
)
class AADSSHLoginForLinuxTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.Azure.ActiveDirectory"
    EXTENSION_TYPE = "AADSSHLoginForLinux"
    EXTENSION_KEY = "aad_ssh_login_for_linux"

    @TestCaseMetadata(
        description="""
        Basic boot validation for the Entra ID SSH login VM extension.

        The handler reads the VM managed identity while enabling, so the case
        first assigns a system-assigned identity, then installs the explicitly
        requested candidate version with empty public settings and no protected
        settings. Verifies that extension provisioning succeeds, the installed
        patch version matches when a full version is supplied, and the VM
        remains reachable before removing the extension.

        No Entra ID role assignments are created, so this validates the handler
        install lifecycle only, not an end-to-end Entra ID SSH sign-in.

        The candidate version is read from the 'extension_version' or
        'aad_ssh_login_for_linux_version' runbook variable.
        """,
        priority=5,
        requirement=simple_requirement(
            supported_features=[AzureExtension],
            supported_platform_type=[AZURE],
            unsupported_os=[BSD, Windows],
        ),
        tags=["microsoft.azure.activedirectory.aadsshloginforlinux"],
        maturity="preview",
    )
    def microsoft_azure_activedirectory_aadsshloginforlinux_boot_validation_test(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        variables: Dict[str, Any],
    ) -> None:
        self._assign_system_identity(node=node, environment=environment, log=log)
        self._boot_validation(
            node=node,
            log=log,
            variables=variables,
            settings={},
        )

    def _assign_system_identity(
        self, node: Node, environment: Environment, log: Logger
    ) -> None:
        platform = environment.platform
        assert isinstance(platform, AzurePlatform)
        node_context = get_node_context(node)
        add_system_assign_identity(
            platform=platform,
            resource_group_name=node_context.resource_group_name,
            vm_name=node_context.vm_name,
            location=node_context.location,
            log=log,
        )
