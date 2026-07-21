# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict, Optional

from assertpy import assert_that
from retry import retry

from lisa import Logger, Node, TestSuite
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.util import SkippedException


class VmExtensionTestBase(TestSuite):
    """
    Base class for publisher-owned VM extension test suites.

    Subclasses MUST define:
      - PUBLISHER: str       — e.g. "Microsoft.Azure.Extensions"
      - EXTENSION_TYPE: str  — e.g. "CustomScript"
      - EXTENSION_KEY: str   — e.g. "custom_script" (snake_case, unique)

    The extension version is always read from a runbook variable named
    '{EXTENSION_KEY}_version'. This allows multiple extensions to be
    tested in a single run without code changes.
    """

    PUBLISHER: str = ""
    EXTENSION_TYPE: str = ""
    EXTENSION_KEY: str = ""

    @property
    def version_variable(self) -> str:
        """Runbook variable name for this extension's version."""
        return f"{self.EXTENSION_KEY}_version"

    @property
    def extension_name(self) -> str:
        """Azure resource name used when installing the extension."""
        return self.EXTENSION_KEY

    def _get_version(self, variables: Dict[str, Any]) -> str:
        """
        Read the extension version from runbook variables.
        Raises SkippedException if not set — the test is not applicable
        for this run.
        """
        version = str(variables.get(self.version_variable, "")).strip()
        if not version:
            raise SkippedException(
                f"Runbook variable '{self.version_variable}' is required for "
                f"{self.PUBLISHER}.{self.EXTENSION_TYPE}. Skipping."
            )
        return version

    @retry(tries=3, delay=10)  # type: ignore
    def _install(
        self,
        node: Node,
        variables: Dict[str, Any],
        settings: Optional[Dict[str, Any]] = None,
        protected_settings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Install the extension on the node. Pre-deletes any existing instance
        with the same name to avoid conflicts.
        """
        version = self._get_version(variables)
        extension = node.features[AzureExtension]
        extension.delete(name=self.extension_name, ignore_not_found=True)
        result: Dict[str, Any] = extension.create_or_update(
            name=self.extension_name,
            publisher=self.PUBLISHER,
            type_=self.EXTENSION_TYPE,
            type_handler_version=version,
            auto_upgrade_minor_version=True,
            settings=settings or {},
            protected_settings=protected_settings or {},
        )
        return result

    def _assert_provisioned(self, result: Dict[str, Any]) -> None:
        """Assert the extension provisioning state is Succeeded."""
        assert_that(result["provisioning_state"]).described_as(
            f"Expected {self.PUBLISHER}.{self.EXTENSION_TYPE} "
            f"provisioning to succeed"
        ).is_equal_to("Succeeded")

    @retry(tries=3, delay=10)  # type: ignore
    def _uninstall(self, node: Node) -> None:
        """Remove the extension from the node."""
        extension = node.features[AzureExtension]
        extension.delete(name=self.extension_name, ignore_not_found=True)

    def _assert_vm_reachable(self, node: Node) -> None:
        """Verify the VM is still reachable via SSH after extension operations."""
        assert_that(node.test_connection()).described_as(
            "Expected VM to be reachable after extension operation"
        ).is_true()

    def _full_lifecycle(
        self,
        node: Node,
        log: Logger,
        variables: Dict[str, Any],
        settings: Optional[Dict[str, Any]] = None,
        protected_settings: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Standard extension lifecycle validation:
          1. Install extension
          2. Assert provisioning succeeded
          3. Verify VM is reachable
          4. Uninstall extension
          5. Verify VM is still reachable

        Use this in publisher suites for basic lifecycle coverage.
        Do NOT duplicate this logic in individual test methods.
        """
        result = self._install(
            node, variables, settings=settings, protected_settings=protected_settings
        )
        try:
            self._assert_provisioned(result)
            log.info(
                f"Extension '{self.extension_name}' "
                f"({self.PUBLISHER}.{self.EXTENSION_TYPE}) provisioned successfully."
            )
            self._assert_vm_reachable(node)
        finally:
            self._uninstall(node)
        self._assert_vm_reachable(node)
