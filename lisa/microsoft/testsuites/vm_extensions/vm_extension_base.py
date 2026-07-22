# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict, Optional

from assertpy import assert_that
from microsoft.testsuites.vm_extensions.runtime_extensions.common import execute_command
from retry import retry

from lisa import Logger, Node, TestSuite
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.util import SkippedException


class VmExtensionTestBase(TestSuite):
    """
    Base class for publisher-owned VM extension test suites.

    Supports two usage patterns:

    1. **Dedicated suite** — subclass sets class constants:
       - PUBLISHER: str       — e.g. "Microsoft.Azure.Extensions"
       - EXTENSION_TYPE: str  — e.g. "CustomScript"
       - EXTENSION_KEY: str   — e.g. "custom_script" (snake_case, unique)
       Version is read from runbook variable '{EXTENSION_KEY}_version'.

    2. **Generic suite** — leave class constants empty, pass via runbook
       variables:
       - extension_publisher: str
       - extension_type: str
       - extension_version: str
       This is the existing contract used by generic VM extension tests.

    When class constants are set they take precedence over runbook variables.
    """

    PUBLISHER: str = ""
    EXTENSION_TYPE: str = ""
    EXTENSION_KEY: str = ""
    # Optional code-level fallback version, used when the runbook variable
    # '{EXTENSION_KEY}_version' is not provided. Leave empty to require the
    # variable (the test is skipped when neither is set).
    DEFAULT_VERSION: str = ""
    # Whether the extension can be removed with a normal 'Delete VM Extension'
    # operation. Set to False for CRP-managed extensions (e.g. RunCommand v2 /
    # RunCommandHandlerLinux) that cannot be deleted this way.
    SUPPORTS_DELETE: bool = True

    def _resolve_publisher(self, variables: Dict[str, Any]) -> str:
        """Return publisher from runbook variable, falling back to class constant."""
        return variables.get("extension_publisher", "").strip() or self.PUBLISHER

    def _resolve_type(self, variables: Dict[str, Any]) -> str:
        """Return extension type from runbook variable, falling back to class constant."""
        return variables.get("extension_type", "").strip() or self.EXTENSION_TYPE

    def _validate_extension_variables(self, variables: Dict[str, Any]) -> None:
        """
        Validate that if any extension_* runbook variable is provided,
        all three (extension_publisher, extension_type, extension_version)
        are present. This matches the existing GenericVmExtension contract.
        Raises SkippedException on partial specification.

        Note: The extension_* runbook variable approach is maintained for
        backward compatibility with existing runbooks and pipelines that
        use the generic VM extension test contract.
        """
        pub = variables.get("extension_publisher", "").strip()
        ext_type = variables.get("extension_type", "").strip()
        ver = variables.get("extension_version", "").strip()

        # If any generic variable is set, require all three
        if any([pub, ext_type, ver]) and not all([pub, ext_type, ver]):
            missing = []
            if not pub:
                missing.append("extension_publisher")
            if not ext_type:
                missing.append("extension_type")
            if not ver:
                missing.append("extension_version")
            raise SkippedException(
                f"Partial extension_* specification: missing {missing}. "
                f"When using generic runbook variables, all of "
                f"'extension_publisher', 'extension_type', and "
                f"'extension_version' are required."
            )

    @property
    def version_variable(self) -> str:
        """Runbook variable name for this extension's version."""
        return f"{self.EXTENSION_KEY}_version"

    @property
    def extension_name(self) -> str:
        """Azure resource name used when installing the extension."""
        return self.EXTENSION_KEY or self.EXTENSION_TYPE or "vm_extension"

    def _get_version(self, variables: Dict[str, Any]) -> str:
        """
        Resolve the extension version.

        Order of precedence:
          1. runbook variable 'extension_version' (generic suite / override);
          2. runbook variable '{EXTENSION_KEY}_version' (dedicated suite);
          3. the suite's DEFAULT_VERSION code-level fallback.
        Raises SkippedException only if none is set.
        """
        self._validate_extension_variables(variables)
        # Generic variable takes priority
        version = str(variables.get("extension_version", "")).strip()
        # Then dedicated suite variable
        if not version and self.EXTENSION_KEY:
            version = str(variables.get(self.version_variable, "")).strip()
        # Then code-level fallback
        if not version:
            version = self.DEFAULT_VERSION.strip()
        if not version:
            publisher = self._resolve_publisher(variables)
            type_ = self._resolve_type(variables)
            raise SkippedException(
                f"No version set for {publisher}.{type_}: "
                f"runbook variable 'extension_version' or "
                f"'{self.version_variable}' is empty and no "
                f"DEFAULT_VERSION is defined. Skipping."
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
        publisher = self._resolve_publisher(variables)
        type_ = self._resolve_type(variables)
        version = self._get_version(variables)
        extension = node.features[AzureExtension]
        extension.delete(name=self.extension_name, ignore_not_found=True)
        result: Dict[str, Any] = extension.create_or_update(
            name=self.extension_name,
            publisher=publisher,
            type_=type_,
            type_handler_version=version,
            auto_upgrade_minor_version=True,
            settings=settings or {},
            protected_settings=protected_settings or {},
        )
        return result

    def _assert_provisioned(
        self, result: Dict[str, Any], variables: Optional[Dict[str, Any]] = None
    ) -> None:
        """Assert the extension provisioning state is Succeeded."""
        variables = variables or {}
        publisher = self._resolve_publisher(variables)
        type_ = self._resolve_type(variables)
        assert_that(result["provisioning_state"]).described_as(
            f"Expected {publisher}.{type_} provisioning to succeed"
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
        publisher = self._resolve_publisher(variables)
        type_ = self._resolve_type(variables)
        try:
            self._assert_provisioned(result, variables)
            log.info(
                f"Extension '{self.extension_name}' "
                f"({publisher}.{type_}) provisioned successfully."
            )
            self._assert_vm_reachable(node)
        finally:
            self._uninstall(node)
        self._assert_vm_reachable(node)

    def _create_and_verify_extension_run(
        self,
        node: Node,
        variables: Dict[str, Any],
        settings: Optional[Dict[str, Any]] = None,
        protected_settings: Optional[Dict[str, Any]] = None,
        test_file: Optional[str] = None,
        expected_exit_code: Optional[int] = None,
        assert_exception: Optional[Any] = None,
    ) -> None:
        """
        Install the extension and verify the outcome.

          - assert_exception set: expect create_or_update to raise it.
          - otherwise: expect provisioning_state to be 'Succeeded'.
          - test_file + expected_exit_code set: verify the command result on
            the VM via execute_command.

        Any pre-existing instance with the same name is deleted first, unless
        SUPPORTS_DELETE is False (e.g. CRP-managed extensions such as
        RunCommand v2).
        """
        publisher = self._resolve_publisher(variables)
        type_ = self._resolve_type(variables)
        version = self._get_version(variables)
        extension = node.features[AzureExtension]
        if self.SUPPORTS_DELETE:
            extension.delete(name=self.extension_name, ignore_not_found=True)

        def enable_extension() -> Any:
            return extension.create_or_update(
                name=self.extension_name,
                publisher=publisher,
                type_=type_,
                type_handler_version=version,
                auto_upgrade_minor_version=True,
                settings=settings or {},
                protected_settings=protected_settings or {},
            )

        if assert_exception:
            assert_that(enable_extension).raises(assert_exception).when_called_with()
        else:
            result = enable_extension()
            assert_that(result["provisioning_state"]).described_as(
                "Expected the extension to succeed"
            ).is_equal_to("Succeeded")

        if test_file is not None and expected_exit_code is not None:
            execute_command(
                file_name=test_file, expected_exit_code=expected_exit_code, node=node
            )
