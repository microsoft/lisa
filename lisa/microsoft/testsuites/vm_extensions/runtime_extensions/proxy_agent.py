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
    This test suite tests the functionality of the Azure Guest Proxy Agent
    VM extension (Microsoft.Cplat.ProxyAgent.ProxyAgentLinux).

    The extension requires no public or protected settings, so coverage starts
    with boot validation: install the extension with empty settings, confirm
    provisioning succeeds, confirm the requested version was installed, confirm
    the VM is still reachable over SSH, then remove the extension.
    """,
    tags=["VM_Extension", "ProxyAgentLinux"],
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        unsupported_os=[BSD],
    ),
)
class ProxyAgentTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.Cplat.ProxyAgent"
    EXTENSION_TYPE = "ProxyAgentLinux"
    EXTENSION_KEY = "proxy_agent"
    DEFAULT_VERSION = "1.0"

    @TestCaseMetadata(
        description="""
        Basic boot validation for the Guest Proxy Agent VM extension.

        Installs the extension with empty settings, since the Proxy Agent needs
        neither public nor protected settings. Verifies that provisioning
        succeeds and that the VM is still reachable, then removes the extension.

        The extension publisher and type are read from runbook variables
        (extension_publisher, extension_type), defaulting to the Guest Proxy
        Agent extension. The version is required and read from the
        'proxy_agent_version' (or generic 'extension_version') runbook variable;
        the test is skipped if neither is set. The deployed extension is named
        '<publisher>_<extension_type>_boot_validation_test'.
        """,
        priority=5,
        maturity="preview",
    )
    def MICROSOFT_CPLAT_PROXYAGENT_PROXYAGENTLINUX_boot_validation_test(  # noqa: N802
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._boot_validation(
            node=node,
            log=log,
            variables=variables,
            settings={},
        )
