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
from lisa.tools.grep import Grep


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

    _LOG_FILE = "/var/log/azure/applicationhealth-extension/handler.log"
    _EXPECTED_HEALTH_MESSAGE = "Committed health state is healthy"
    # The handler commits the health state asynchronously after provisioning
    # succeeds, so the log message may not be present immediately. Poll the
    # handler log up to 5 times at 60-second intervals (~5 minutes total) to
    # tolerate this propagation window.
    _HEALTH_LOG_RETRIES = 5
    _HEALTH_LOG_DELAY_SECONDS = 60

    @TestCaseMetadata(
        description="""
        Boot validation for the Application Health Extension (AHE) on Linux.

        Installs the explicitly requested candidate version with empty public
        settings and no protected settings. Verifies that extension provisioning
        succeeds, the installed patch version matches when a full version is
        supplied, and the VM remains reachable. While the extension is still
        installed it also confirms the handler log reports a healthy committed
        health state, then removes the extension.

        The candidate version is read from the 'extension_version' or
        'application_health_linux_version' runbook variable.
        """,
        priority=5,
        requirement=simple_requirement(
            supported_features=[AzureExtension],
            supported_platform_type=[AZURE],
            unsupported_os=[BSD, Windows],
        ),
        tags=["microsoft.managedservices.applicationhealthlinux"],
        maturity="preview",
    )
    def microsoft_managedservices_applicationhealthlinux_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._boot_validation(
            node=node,
            log=log,
            variables=variables,
            settings={},
            post_provision=self._verify_committed_health_state,
        )

    @retry(tries=_HEALTH_LOG_RETRIES, delay=_HEALTH_LOG_DELAY_SECONDS)  # type: ignore
    def _verify_committed_health_state(self, node: Node) -> None:
        matches = node.tools[Grep].search(
            pattern=self._EXPECTED_HEALTH_MESSAGE,
            file=self._LOG_FILE,
            sudo=True,
            force_run=True,
        )
        assert_that(matches).described_as(
            f"Expected to find '{self._EXPECTED_HEALTH_MESSAGE}' in "
            f"{self._LOG_FILE}. Verify the Application Health extension "
            f"provisioned healthily and that the handler log exists at this path."
        ).is_not_empty()
