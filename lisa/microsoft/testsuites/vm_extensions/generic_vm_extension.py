from typing import Any, Dict

from assertpy import assert_that
from retry import retry

from lisa import (
    Logger,
    Node,
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
        priority=2,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_vm_extension_install_uninstall(
        self,
        log: Logger,
        node: Node,
        variables: Dict[str, Any],
    ) -> None:
        publisher: str = variables["extension_publisher"]
        type_: str = variables["extension_type"]
        version: str = variables["extension_version"]

        extension = node.features[AzureExtension]
        extension_name = f"{publisher}.{type_}-{version}"

        # Remove any existing extension with the same handler type to avoid
        # conflicts (Azure forbids two extensions with the same publisher+type
        # but different versions on the same VM).
        self._cleanup_existing_extensions(extension, publisher, type_, log)

        extension_result = self._install_extension(
            extension, extension_name, publisher, type_, version
        )

        assert_that(extension_result["provisioning_state"]).described_as(
            "Found the extension provisioning state unexpectedly not Succeeded"
        ).is_equal_to("Succeeded")

        assert_that(self._check_exist(extension, extension_name)).described_as(
            "Found the VM Extension unexpectedly not exists on the VM after"
            "installation"
        ).is_true()

        # Verify the VM is still reachable after extension operations.
        assert_that(node.test_connection()).described_as(
            "Found the VM unexpectedly not reachable via SSH after extension install"
        ).is_true()

        # if extension installed by test then delete the extension
        self._delete_extension(extension, extension_name)

        assert_that(self._check_exist(extension, extension_name)).described_as(
            "Found the VM Extension still unexpectedly exists on the VM after deletion"
        ).is_false()

        # Verify the VM is still reachable after extension operations.
        assert_that(node.test_connection()).described_as(
            "Found the VM unexpectedly not reachable via SSH after extension uninstall"
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
