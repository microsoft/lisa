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
from lisa.sut_orchestrator.azure.common import (
    check_or_create_storage_account,
    get_or_create_storage_container,
    get_storage_credential,
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
        """,
        priority=3,
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
        information = environment.get_information()
        resource_group_name = information["resource_group_name"]
        location = information["location"]

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
        self._container_client = get_or_create_storage_container(
            credential=platform.credential,
            subscription_id=platform.subscription_id,
            cloud=platform.cloud,
            account_name=storage_account_name,
            container_name="azdiagextnresults",
            resource_group_name=resource_group_name,
        )

        blob_iter = self._container_client.list_blobs(
            name_starts_with="PerformanceDiagnostics"
        )

        report_exists = False
        for _ in blob_iter:
            report_exists = True

        assert_that(report_exists).is_true()

        # Delete VM Extension
        extension.delete("AzurePerformanceDiagnosticsLinux")

        assert_that(
            extension.check_exist("AzurePerformanceDiagnosticsLinux")
        ).is_false()

    def _is_supported_linux_distro(self, node: Node) -> bool:
        supported_major_versions = {
            "redhat": [7, 8],
            "red hat": [7, 8],
            "centos": [6, 7],
            "oracle": [6, 7],
            "debian": [8, 9, 10, 11],
            "ubuntu": [14, 16, 18, 20],
            "suse": [12, 15],
            "sles": [12, 15],
            "almalinux": [8],
            "mariner": [2],
        }

        version_list = supported_major_versions.get(
            (node.os.information.vendor).lower()
        )

        if (
            version_list is not None
            and node.os.information.version.major in version_list
            and not self._is_unsupported_version(node)
        ):
            return True
        else:
            return False

    def _is_unsupported_version(self, node: Node) -> bool:
        """
        These are specific Linux distro versions that are
        not supported by Azure Performance Diagnostics,
        even though the major version is generally supported
        """
        unsupported_versions = {
            "redhat": [{"major": 8, "minor": 0}],
            "red hat": [{"major": 8, "minor": 0}],
        }

        unsupported_versions_list = unsupported_versions.get(
            (node.os.information.vendor).lower()
        )
        if unsupported_versions_list:
            for version in unsupported_versions_list:
                if node.os.information.version.major == version.get(
                    "major"
                ) and node.os.information.version.minor == version.get("minor"):
                    return True

        return False
