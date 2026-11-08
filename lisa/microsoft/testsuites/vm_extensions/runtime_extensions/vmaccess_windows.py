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
    This test suite validates the Windows VMAccess VM extension
    (Microsoft.Compute.VMAccessAgent).
    """,
    tags=["VM_Extension", "VMAccessAgent"],
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        supported_os=[Windows],
    ),
)
class VMAccessWindowsTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.Compute"
    EXTENSION_TYPE = "VMAccessAgent"
    EXTENSION_KEY = "vmaccess_windows"

    @TestCaseMetadata(
        description="""
        Boot validation for the Windows VMAccess VM extension.

        Installs the explicitly requested candidate version with empty public
        settings and no protected settings to reset RDP configuration without
        changing the account or credentials used by LISA. Verifies provisioning
        succeeds, the installed version matches when a full candidate version
        is supplied, and the VM remains reachable, then removes the extension.

        The node is marked dirty before installation because removing the
        extension does not undo the RDP and firewall configuration changes.
        Domain controllers are not supported by this extension.

        The candidate version is read from 'extension_version' or
        'vmaccess_windows_version'.
        """,
        priority=5,
        tags=["microsoft.compute.vmaccessagent"],
        maturity="preview",
    )
    def microsoft_compute_vmaccessagent_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._boot_validation(
            node=node,
            log=log,
            variables=variables,
            settings={},
            mark_dirty_before_install=True,
        )
