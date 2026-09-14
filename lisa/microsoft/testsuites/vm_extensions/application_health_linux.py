# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict

from assertpy import assert_that
from microsoft.testsuites.vm_extensions.vm_extension_base import VmExtensionTestBase
from retry import retry

from lisa import Logger, Node, TestCaseMetadata, TestSuiteMetadata, simple_requirement
from lisa.operating_system import BSD, Windows
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.features import AzureExtension


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    This test suite validates the Microsoft Application Health Extension (AHE)
    on Linux (Microsoft.ManagedServices.ApplicationHealthLinux).
    """,
    tags=["VM_Extension", "ApplicationHealthLinux"],
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        unsupported_os=[BSD, Windows],
    ),
)
class ApplicationHealthLinuxTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.ManagedServices"
    EXTENSION_TYPE = "ApplicationHealthLinux"
    EXTENSION_KEY = "application_health_linux"
    # Code-level fallback version used when neither 'extension_version' nor
    # 'application_health_linux_version' runbook variables are provided.
    DEFAULT_VERSION = "2.0"

    _LOG_FILE = "/var/log/azure/applicationhealth-extension/handler.log"
    _EXPECTED_HEALTH_MESSAGE = "Committed health state is healthy"

    @TestCaseMetadata(
        description="""
        Functional validation for the Application Health Extension (AHE) on
        Linux.

        Installs the extension, verifies that provisioning succeeds, confirms
        the handler log reports a healthy committed health state, checks the VM
        is still reachable over SSH, then removes the extension.

        The extension publisher and type are read from runbook variables
        (extension_publisher, extension_type), defaulting to the Application
        Health Extension. The version is read from the
        'application_health_linux_version' (or generic 'extension_version')
        runbook variable, falling back to the suite's DEFAULT_VERSION.
        """,
        priority=5,
        tags=["microsoft.managedservices.applicationhealthlinux"],
        maturity="preview",
    )
    def microsoft_managedservices_applicationhealthlinux_functional_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        publisher = self._resolve_publisher(variables)
        type_ = self._resolve_type(variables)
        log.info(f"Installing extension '{self.extension_name}' ({publisher}.{type_})")

        result = self._install(node, variables, settings={})
        try:
            self._assert_provisioned(result, variables)
            log.info(
                f"Extension '{self.extension_name}' provisioned successfully; "
                "verifying committed health state."
            )
            self._check_extension_logs(
                node=node,
                log_file=self._LOG_FILE,
                expected_app_health_message=self._EXPECTED_HEALTH_MESSAGE,
            )
            self._assert_vm_reachable(node)
        finally:
            self._uninstall(node)
        self._assert_vm_reachable(node)

    @retry(tries=5, delay=60)  # type: ignore
    def _check_extension_logs(
        self, node: Node, log_file: str, expected_app_health_message: str
    ) -> None:
        result = node.execute(
            f"grep '{expected_app_health_message}' {log_file}", sudo=True
        )
        assert_that(result.exit_code).described_as(
            f"Expected to find '{expected_app_health_message}' in {log_file}"
        ).is_equal_to(0)
