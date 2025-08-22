# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import json
import string
import time
from typing import Any, Dict, List

from assertpy import assert_that
from azure.mgmt.keyvault.models import AccessPolicyEntry, Permissions
from azure.mgmt.keyvault.models import Sku as KeyVaultSku
from azure.mgmt.keyvault.models import VaultProperties

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.features.security_profile import CvmDisabled
from lisa.operating_system import CBLMariner, CentOs, Oracle, Redhat, Ubuntu
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    AzureNodeSchema,
    create_keyvault,
    get_identity_id,
    get_matching_key_vault_name,
    get_tenant_id,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform, AzurePlatformSchema
from lisa.testsuite import TestResult, simple_requirement
from lisa.util import (
    SkippedException,
    UnsupportedDistroException,
    generate_random_chars,
)

TIME_LIMIT = 3600 * 2
MIN_REQUIRED_MEMORY_MB = 8 * 1024

# Define a type alias for readability
UnsupportedVersionInfo = List[Dict[str, int]]


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="Tests for the Azure Disk Encryption (ADE) extension",
)
class AzureDiskEncryption(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        if not self._is_supported_linux_distro(node):
            raise SkippedException(UnsupportedDistroException(node.os))
        needed_packages = ["python-parted", "python3-parted"]
        for package in needed_packages:
            if node.os.is_package_in_repo(package):
                node.os.install_packages(package)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        # Disk Encryption may cause node to be in bad state
        # some time after the test case is done. This can cause
        # subsequent test cases to fail when environment is reused.
        # Hence, mark the node as dirty.
        node = kwargs["node"]
        node.mark_dirty()

    @TestCaseMetadata(
        description="""
        Runs the ADE extension and verifies it
        fully encrypted the remote machine successfully.
        """,
        priority=3,
        timeout=TIME_LIMIT,
        requirement=simple_requirement(
            min_memory_mb=MIN_REQUIRED_MEMORY_MB,
            supported_features=[AzureExtension, CvmDisabled()],
            supported_platform_type=[AZURE],
            min_core_count=4,
        ),
    )
    def verify_azure_disk_encryption_enabled(
        self, log: Logger, node: Node, result: TestResult
    ) -> None:
        extension_result = self._enable_ade_extension(node, log, result)
        assert_that(extension_result["provisioning_state"]).described_as(
            "Expected the extension to succeed"
        ).is_equal_to("Succeeded")

        # Get VM Extension status
        # Maximum time to check is 3 hours, which is 180 minutes.
        # We're checking every 5 minutes, so the loop will run 180/5 = 36 times.
        max_retries = 36
        retry_interval = 300  # 5 minutes in seconds
        os_status = None
        extension = node.features[AzureExtension]
        extension_status = extension.get(name="AzureDiskEncryptionForLinux")
        instance_view = extension_status.instance_view
        substatuses = instance_view.substatuses
        log.debug(f"Extension status: {extension_status}")
        log.debug(f"Instance view: {instance_view}")

        for i in range(max_retries):
            extension_status = extension.get(name="AzureDiskEncryptionForLinux")
            instance_view = extension_status.instance_view
            substatuses = instance_view.substatuses
            for substatus in substatuses:
                log.debug(f"Substatus: {substatus}")
                try:
                    message_json = json.loads(substatus.message)
                    os_status = message_json.get("os")
                    if os_status == "Encrypted":
                        log.debug("The 'os' status is 'Encrypted'")
                        break
                except json.JSONDecodeError:
                    log.error(f"Failed to parse message content: {substatus.message}")

            # If the os_status is 'Encrypted', break out of the loop
            if os_status == "Encrypted":
                break

            # Otherwise, sleep for 5 minutes before checking again
            if i < max_retries - 1:  # To avoid sleeping after the last iteration
                log.debug(
                    f"Sleeping for {retry_interval} seconds before checking again"
                )
                log.debug(f"Retry #{i + 1} of {max_retries}")
                time.sleep(retry_interval)

        assert_that(os_status).described_as(
            "Expected the OS status to be 'Encrypted'"
        ).is_equal_to("Encrypted")

    @TestCaseMetadata(
        description="""
        Runs the ADE extension and verifies the extension
        provisioned successfully on the remote machine.
        """,
        priority=1,
        requirement=simple_requirement(
            min_memory_mb=MIN_REQUIRED_MEMORY_MB,
            supported_features=[AzureExtension, CvmDisabled()],
            supported_platform_type=[AZURE],
        ),
    )
    def verify_azure_disk_encryption_provisioned(
        self, log: Logger, node: Node, result: TestResult
    ) -> None:
        extension_result = self._enable_ade_extension(node, log, result)

        assert_that(extension_result["provisioning_state"]).described_as(
            "Expected the extension to succeed"
        ).is_equal_to("Succeeded")

    def _enable_ade_extension(self, node: Node, log: Logger, result: TestResult) -> Any:
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        platform = environment.platform
        assert isinstance(platform, AzurePlatform)
        runbook = platform.runbook.get_extended_runbook(AzurePlatformSchema)
        tenant_id = get_tenant_id(platform.credential)
        if tenant_id is None:
            raise ValueError("Environment variable 'tenant_id' is not set.")
        application_id = runbook.service_principal_client_id
        object_id = get_identity_id(platform=platform, application_id=application_id)
        if object_id is None:
            raise ValueError("Environment variable 'object_id' is not set.")

        node_capability = node.capability.get_extended_runbook(AzureNodeSchema, AZURE)
        location = node_capability.location
        shared_resource_group = runbook.shared_resource_group_name

        # Create key vault if there is not available lisa-ade key vault for that region
        existing_vault = get_matching_key_vault_name(
            platform, location, shared_resource_group, r"lisa-ade-\w{5}"
        )
        if existing_vault:
            vault_name = existing_vault
        else:
            random_str = generate_random_chars(
                string.ascii_lowercase + string.digits, 5
            )
            vault_name = f"lisa-ade-{random_str}"

        vault_properties = VaultProperties(
            tenant_id=tenant_id,
            sku=KeyVaultSku(name="standard"),
            enabled_for_disk_encryption=True,
            access_policies=[
                AccessPolicyEntry(
                    tenant_id=tenant_id,
                    object_id=object_id,
                    permissions=Permissions(
                        keys=["all"], secrets=["all"], certificates=["all"]
                    ),
                ),
            ],
        )
        # If the KV exists, this will just ensure the properties are correct for ADE
        keyvault_result = create_keyvault(
            platform=platform,
            location=location,
            vault_name=vault_name,
            resource_group_name=shared_resource_group,
            vault_properties=vault_properties,
        )

        # Check if KeyVault is successfully created or updated before proceeding
        assert (
            keyvault_result
        ), f"Failed to create or update KeyVault with name: {vault_name}"

        # Run ADE Extension
        extension_name = "AzureDiskEncryptionForLinux"
        extension_publisher = "Microsoft.Azure.Security"
        extension_version = "1.4"
        settings = {
            "EncryptionOperation": "EnableEncryption",
            "KeyVaultURL": keyvault_result.properties.vault_uri,
            "KeyVaultResourceId": keyvault_result.id,
            "KeyEncryptionAlgorithm": "RSA-OAEP",
            "VolumeType": "Os",
        }
        extension = node.features[AzureExtension]
        extension_result = extension.create_or_update(
            name=extension_name,
            publisher=extension_publisher,
            type_=extension_name,
            type_handler_version=extension_version,
            settings=settings,
        )
        return extension_result

    def _is_supported_linux_distro(self, node: Node) -> bool:
        minimum_supported_major_versions = {
            Redhat: 7,
            CentOs: 7,
            Oracle: 8,
            Ubuntu: 18,
            CBLMariner: 2,
        }
        # Remove after automatic major version support is released to ADE
        max_supported_major_versions = {
            Redhat: 9,
            CentOs: 8,
            Oracle: 8,
            Ubuntu: 22,
            CBLMariner: 2,
        }

        if self._is_unsupported_minor_version(node):
            return False

        for distro, max_supported_version in max_supported_major_versions.items():
            if type(node.os) is distro:
                if node.os.information.version.major > max_supported_version:
                    return False

        for distro, min_supported_version in minimum_supported_major_versions.items():
            if type(node.os) is distro:
                if node.os.information.version.major >= min_supported_version:
                    return True

        return False

    def _is_unsupported_minor_version(self, node: Node) -> bool:
        min_supported_versions: Dict[type, UnsupportedVersionInfo] = {
            Oracle: [{"major": 8, "minor": 5}],
            CentOs: [{"major": 8, "minor": 1}, {"major": 7, "minor": 4}],
            Redhat: [{"major": 8, "minor": 1}, {"major": 7, "minor": 4}],
        }

        version_info = node.os.information.version
        major_version = version_info.major
        minor_version = version_info.minor

        # ADE support only on Ubuntu LTS images
        if type(node.os) is Ubuntu:
            if minor_version != 4:
                return True

        for distro, versions in min_supported_versions.items():
            if type(node.os) is distro:
                for version in versions:
                    if (
                        major_version == version["major"]
                        and minor_version < version["minor"]
                    ):
                        return True

        return False
