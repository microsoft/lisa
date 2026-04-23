from typing import Any, Dict

from assertpy import assert_that
from retry import retry

from lisa import (
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.sut_orchestrator.azure.features import AzureExtension


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description=(
        "Generic test for validating VM extension install and uninstall. "
        "Extension publisher, type, and version are provided via runbook variables."
    ),
    tags=["VM_Extension"],
)
class GenericVmExtension(TestSuite):
    @TestCaseMetadata(
        description="""
        Generic test case that installs a VM extension specified via runbook
        variables, verifies provisioning succeeds, uninstalls the extension,
        and confirms the VM is still reachable afterwards.

        Required runbook variables:
          - extension_publisher  (e.g. "Microsoft.Azure.Monitor")
          - extension_type       (e.g. "AzureMonitorLinuxAgent")
          - extension_version    (e.g. "1.0")
        """,
        priority=3,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_vm_extension_install_uninstall(
        self,
        log: Logger,
        node: Node,
        variables: Dict[str, Any],
    ) -> None:
        publisher: str = variables.get("extension_publisher", "").strip()
        type_: str = variables.get("extension_type", "").strip()
        version: str = variables.get("extension_version", "").strip()

        if not publisher or not type_ or not version:
            raise SkippedException(
                "Required runbook variable(s) are missing or empty: "
                f"extension_publisher='{publisher}', "
                f"extension_type='{type_}', "
                f"extension_version='{version}'. "
                "Please set them in the runbook before running this test case."
            )

        extension = node.features[AzureExtension]
        extension_name = f"{publisher}.{type_}-{version}"
        install_version, is_patch_version = extension.normalize_type_handler_version(
            version
        )

        # Remove any existing extension with the same handler type to avoid
        # conflicts (Azure forbids two extensions with the same publisher+type
        # but different versions on the same VM).
        self._cleanup_existing_extensions(extension, publisher, type_, log)

        extension_result = self._install_extension(
            extension, extension_name, publisher, type_, install_version
        )

        assert_that(extension_result["provisioning_state"]).described_as(
            "Expected extension provisioning state to be Succeeded"
        ).is_equal_to("Succeeded")

        assert_that(self._check_exist(extension, extension_name)).described_as(
            "Expected VM extension to exist after installation"
        ).is_true()

        installed_version = extension.get_installed_type_handler_version(extension_name)
        if is_patch_version:
            assert_that(installed_version).described_as(
                f"Installed extension '{extension_name}' version mismatch: expected "
                f"'{version}', actual '{installed_version}'. Verify which patch "
                f"version Azure delivers for the requested major.minor version and "
                f"check whether this extension version is published in the current "
                f"region."
            ).is_equal_to(version)

        log.info(f"Installed extension '{extension_name}' version: {installed_version}")

        # Verify the VM is still reachable after extension operations.
        assert_that(node.test_connection()).described_as(
            "Expected VM to be reachable via SSH after extension installation"
        ).is_true()

        # if extension installed by test then delete the extension
        self._delete_extension(extension, extension_name)

        assert_that(self._check_exist(extension, extension_name)).described_as(
            "Expected VM extension to be removed after deletion"
        ).is_false()

        # Verify the VM is still reachable after extension operations.
        assert_that(node.test_connection()).described_as(
            "Expected VM to be reachable via SSH after extension uninstallation"
        ).is_true()

    @retry(tries=3, delay=10)  # type: ignore
    def _cleanup_existing_extensions(
        self,
        extension: AzureExtension,
        publisher: str,
        type_: str,
        log: Logger,
    ) -> None:
        for ext in extension.list_all():
            if (
                getattr(ext, "publisher", None) == publisher
                and getattr(ext, "type_properties_type", None) == type_
            ):
                log.info(
                    f"Deleting pre-existing extension '{ext.name}' "
                    f"with same handler type '{publisher}.{type_}'."
                )
                extension.delete(name=ext.name)

    @retry(tries=3, delay=10)  # type: ignore
    def _install_extension(
        self,
        extension: AzureExtension,
        name: str,
        publisher: str,
        type_: str,
        version: str,
    ) -> Any:
        return extension.create_or_update(
            name=name,
            publisher=publisher,
            type_=type_,
            type_handler_version=version,
        )

    @retry(tries=3, delay=10)  # type: ignore
    def _delete_extension(
        self,
        extension: AzureExtension,
        name: str,
        ignore_not_found: bool = False,
    ) -> None:
        extension.delete(name=name, ignore_not_found=ignore_not_found)

    @retry(tries=3, delay=10)  # type: ignore
    def _check_exist(
        self,
        extension: AzureExtension,
        name: str,
    ) -> bool:
        return extension.check_exist(name)
