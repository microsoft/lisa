import string
from datetime import datetime, timezone
from typing import Any

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import (
    SLES,
    AlmaLinux,
    CBLMariner,
    CentOs,
    Debian,
    Oracle,
    Redhat,
    Suse,
    Ubuntu,
)
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    AzureNodeSchema,
    check_or_create_storage_account,
    get_node_context,
    get_storage_credential,
    list_blobs,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.testsuite import TestResult
from lisa.util import SkippedException, generate_random_chars


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="Tests for the Azure Performance Diagnostics VM Extension",
)
class AzurePerformanceDiagnostics(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        if not self._is_supported_linux_distro(node):
            raise SkippedException(
                f"{str(node.os.information.full_version)} is not supported."
            )

    @TestCaseMetadata(
        description="""
        Installs and runs the Azure Performance Diagnostics VM Extension.
        Verifies a report was created and uploaded to the storage account.
        Deletes the VM Extension.

        Downgrading priority from 1 to 5. The extension relies on the
         storage account key, which we cannot use currently.
        Will change it back once the extension works with MSI.
        """,
        priority=5,
        requirement=simple_requirement(
            supported_features=[AzureExtension],
        ),
    )
    def verify_azure_performance_diagnostics(
        self, log: Logger, node: Node, result: TestResult
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        platform = environment.platform
        assert isinstance(platform, AzurePlatform)

        # Create storage account and get credentials
        random_str = generate_random_chars(string.ascii_lowercase + string.digits, 10)
        storage_account_name = f"lisasc{random_str}"
        node_context = get_node_context(node)
        resource_group_name = node_context.resource_group_name
        node_capability = node.capability.get_extended_runbook(AzureNodeSchema, AZURE)
        location = node_capability.location

        check_or_create_storage_account(
            credential=platform.credential,
            subscription_id=platform.subscription_id,
            cloud=platform.cloud,
            account_name=storage_account_name,
            resource_group_name=resource_group_name,
            location=location,
            log=log,
        )

        account_credential = get_storage_credential(
            credential=platform.credential,
            subscription_id=platform.subscription_id,
            cloud=platform.cloud,
            account_name=storage_account_name,
            resource_group_name=resource_group_name,
        )

        # Run VM Extension
        extension = node.features[AzureExtension]
        settings = {
            "performanceScenario": "quick",
            "traceDurationInSeconds": 5,
            "srNumber": "",
            "requestTimeUtc": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f"),
            "storageAccountName": storage_account_name,
            "resourceId": (
                f"/subscriptions/{platform.subscription_id}/resourceGroups/"
                f"{resource_group_name}/providers/Microsoft.Compute/virtualMachines"
                f"/{node.name}"
            ),
        }

        protected_settings = {
            "storageAccountName": storage_account_name,
            "storageAccountKey": account_credential.get("account_key"),
        }

        extension_result = extension.create_or_update(
            name="AzurePerformanceDiagnosticsLinux",
            publisher="Microsoft.Azure.Performance.Diagnostics",
            type_="AzurePerformanceDiagnosticsLinux",
            type_handler_version="1.0",
            auto_upgrade_minor_version=True,
            settings=settings,
            protected_settings=protected_settings,
        )

        assert_that(extension_result["provisioning_state"]).described_as(
            "Expected the extension to succeed"
        ).is_equal_to("Succeeded")

        # Verify report was created and uploaded to the storage account
        blob_iter = list_blobs(
            credential=platform.credential,
            subscription_id=platform.subscription_id,
            cloud=platform.cloud,
            account_name=storage_account_name,
            container_name="azdiagextnresults",
            resource_group_name=resource_group_name,
            name_starts_with="PerformanceDiagnostics",
        )

        report_exists = False
        for _ in blob_iter:
            report_exists = True

        assert_that(report_exists).described_as(
            "Expected to find a report in the storage account, but no report was found"
        ).is_true()

        # Delete VM Extension
        extension.delete("AzurePerformanceDiagnosticsLinux")

        assert_that(
            extension.check_exist("AzurePerformanceDiagnosticsLinux")
        ).described_as(
            "Found the VM Extension still unexpectedly exists on the VM after deletion"
        ).is_false()

    def _is_supported_linux_distro(self, node: Node) -> bool:
        supported_major_versions = {
            Redhat: [7, 8],
            CentOs: [6, 7],
            Oracle: [6, 7],
            Debian: [8, 9, 10, 11],
            Ubuntu: [14, 16, 18, 20],
            Suse: [12, 15],
            SLES: [12, 15],
            AlmaLinux: [8],
            CBLMariner: [2],
        }

        for distro in supported_major_versions:
            if type(node.os) is distro:
                version_list = supported_major_versions.get(distro)
                if (
                    version_list is not None
                    and node.os.information.version.major in version_list
                    and not self._is_unsupported_version(node)
                ):
                    return True
                else:
                    return False
        return False

    def _is_unsupported_version(self, node: Node) -> bool:
        """
        These are specific Linux distro versions that are
        not supported by Azure Performance Diagnostics,
        even though the major version is generally supported
        """
        version = node.os.information.version
        if type(node.os) and (version == "8.0.0" or version == "8.0.1"):
            return True
        else:
            return False
