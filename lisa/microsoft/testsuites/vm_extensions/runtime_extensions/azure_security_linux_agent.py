# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import time
from typing import Any, Dict, Optional

from microsoft.testsuites.vm_extensions.vm_extension_base import VmExtensionTestBase

from lisa import Logger, Node, TestCaseMetadata, TestSuiteMetadata, simple_requirement
from lisa.operating_system import BSD
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.features import AzureExtension


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    This test suite validates the Azure Security Linux Agent VM extension
    (Microsoft.Azure.Security.Monitoring.AzureSecurityLinuxAgent).

    The Azure Security Linux Agent provides security logging and monitoring
    coverage for Linux VMs (Microsoft Defender for Cloud / Azure Security
    Center). It is the mandatory boot validation coverage required for the
    publisher to onboard to Functional Validation.
    """,
    tags=["VM_Extension", "AzureSecurityLinuxAgent"],
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        unsupported_os=[BSD],
    ),
)
class AzureSecurityLinuxAgentTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.Azure.Security.Monitoring"
    EXTENSION_TYPE = "AzureSecurityLinuxAgent"
    EXTENSION_KEY = "azure_security_linux_agent"

    @TestCaseMetadata(
        description="""
        Basic boot validation for the Azure Security Linux Agent VM extension.

        The Azure Security Linux Agent is frequently auto-provisioned on the VM
        (e.g. by Microsoft Defender for Cloud). Because Linux does not support
        more than one VM extension per handler, this case first checks whether
        the handler is already installed:

        * If an instance of the handler is already present, it is validated in
          place: provisioning must be 'Succeeded' and the VM must stay
          reachable over SSH. The installed handler version is logged. No new
          instance is created and the pre-existing (platform-managed) instance
          is left untouched.
        * Otherwise the extension is installed with empty inline settings (the
          agent requires no storage account or public blob access),
          provisioning is asserted, the requested version is verified, VM
          reachability is confirmed, and the instance is removed.

        The extension version is read from runbook variable
        'azure_security_linux_agent_version' (or the generic
        'extension_version'); it is required only for the install path, where
        the case is skipped when neither is set. The deployed extension (install
        path) is named '<publisher>_<extension_type>_boot_validation_test'.
        """,
        priority=1,
        maturity="experimental",
        requirement=simple_requirement(
            supported_features=[AzureExtension],
            supported_platform_type=[AZURE],
            unsupported_os=[BSD],
        ),
    )
    def microsoft_azure_security_monitoring_azuresecuritylinuxagent_boot_validation_test(  # noqa: E501
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        extension = node.features[AzureExtension]
        publisher = self._resolve_publisher(variables)
        type_ = self._resolve_type(variables)

        # Linux allows only one VM extension per handler. If the agent is
        # already installed (commonly auto-provisioned), validate that instance
        # instead of installing a conflicting one.
        existing_name = self._find_installed_handler_name(extension, publisher, type_)
        if existing_name is not None:
            log.info(
                f"Handler '{publisher}.{type_}' is already installed as "
                f"'{existing_name}'; validating the existing instance in place."
            )
            # An auto-provisioned instance may still be mid-provisioning
            # ('Creating'/'Updating') when discovered. Wait for a terminal
            # state before asserting so the check is not racing the platform.
            provisioning_state = self._wait_for_terminal_provisioning_state(
                extension, existing_name, log
            )
            self._assert_provisioned(
                {"provisioning_state": provisioning_state}, variables
            )
            installed_version = extension.get_installed_type_handler_version(
                existing_name
            )
            log.info(
                f"Installed extension '{existing_name}' "
                f"version: {installed_version}"
            )
            self._assert_vm_reachable(node)
            return

        # Not present: the Azure Security Linux Agent installs without inline
        # settings.
        self._boot_validation(node, log, variables, settings={})

    def _find_installed_handler_name(
        self, extension: AzureExtension, publisher: str, type_: str
    ) -> Optional[str]:
        """
        Return the resource name of an already-installed extension matching the
        given publisher and handler type, or None if the handler is not present.
        """
        for ext in extension.list_all() or []:
            ext_publisher = getattr(ext, "publisher", "") or ""
            ext_type = getattr(ext, "type_properties_type", "") or ""
            if ext_publisher == publisher and ext_type == type_:
                name = getattr(ext, "name", "") or ""
                if name:
                    return name
        return None

    def _wait_for_terminal_provisioning_state(
        self,
        extension: AzureExtension,
        name: str,
        log: Logger,
        timeout: int = 600,
        interval: int = 20,
    ) -> str:
        """
        Poll the extension instance until its provisioning state is terminal
        ('Succeeded' or 'Failed'), then return that state. Transient states such
        as 'Creating'/'Updating' happen while the platform is still provisioning
        an auto-installed instance. Returns the last observed state on timeout.
        """
        transient_states = {"creating", "updating", "deleting", ""}
        deadline = time.monotonic() + timeout
        provisioning_state = ""
        while True:
            detail = extension.get(name=name)
            provisioning_state = str(detail.provisioning_state or "")
            if provisioning_state.lower() not in transient_states:
                return provisioning_state
            if time.monotonic() >= deadline:
                log.info(
                    f"Extension '{name}' still in transient state "
                    f"'{provisioning_state}' after {timeout}s; proceeding."
                )
                return provisioning_state
            log.info(
                f"Extension '{name}' provisioning state is "
                f"'{provisioning_state}'; waiting {interval}s for it to settle."
            )
            time.sleep(interval)
