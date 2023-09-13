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
    requirement=simple_requirement(
        min_memory_mb=MIN_REQUIRED_MEMORY_MB,
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
    ),
)
class AzureDiskEncryption(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        result = kwargs["result"]
        image = result.information.get("image")
        if not self._is_supported_linux_distro(node, image):
            raise SkippedException(
                UnsupportedDistroException(
                    node.os, f'OS or Image "{image}" is not compatible with ADE'
                )
            )

    @TestCaseMetadata(
        description="""
        Runs the ADE extension and verifies it
        fully encrypted the remote machine successfully.
        """,
        priority=3,
        timeout=TIME_LIMIT,
        requirement=simple_requirement(
            min_memory_mb=MIN_REQUIRED_MEMORY_MB,
            supported_features=[AzureExtension],
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
                log.debug(f"Retry #{i+1} of {max_retries}")
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

        # Create key vault if there is not available adelisa key vault for that region
        existing_vault = get_matching_key_vault_name(
            platform, location, shared_resource_group, r"adelisa-\w{5}"
        )
        if existing_vault:
            vault_name = existing_vault
        else:
            random_str = generate_random_chars(
                string.ascii_lowercase + string.digits, 5
            )
            vault_name = f"adelisa-{random_str}"

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

    def _is_supported_linux_distro(self, node: Node, image: str) -> bool:
        minimum_supported_major_versions = {
            Redhat: 7,
            CentOs: 7,
            Oracle: 8,
            Ubuntu: 18,
            CBLMariner: 2,
        }

        if self._is_unsupported_version(node, image):
            return False

        for distro, min_supported_version in minimum_supported_major_versions.items():
            if isinstance(node.os, distro):
                if node.os.information.version.major >= min_supported_version:
                    return True

        return False

    def _is_unsupported_version(self, node: Node, image: str) -> bool:
        # List of known bad images that should be skipped
        known_bad_images = [
            # Minimal not supported
            "canonical 0001-com-ubuntu-minimal-kinetic minimal-22_10 22.10.202307010",
            # Missing packages
            "canonical 0001-com-ubuntu-server-focal 20_04-lts 20.04.202007080",
            "canonical 0001-com-ubuntu-server-focal 20_04-lts-gen2 20.04.202308310",
            "canonical 0001-com-ubuntu-server-kinetic 22_10 22.10.202303220",
            "canonical 0001-com-ubuntu-server-kinetic 22_10 22.10.202306190",
            # Ubuntu 23 is not yet supported
            "canonical 0001-com-ubuntu-server-lunar 23_04 23.04.202309050",
            "canonical 0001-com-ubuntu-server-lunar 23_04-arm64 23.04.202309050",
            "canonical 0001-com-ubuntu-server-lunar 23_04-gen2 23.04.202307120",
            "canonical 0001-com-ubuntu-server-lunar 23_04-gen2 23.04.202309050",
            # Some older UB18 images are missing critical ADE packages
            "canonical ubuntuserver 18.04-lts 18.04.202001210",
            "canonical ubuntuserver 18.04-lts 18.04.202006101",
            "canonical ubuntuserver 18.04-lts 18.04.202306070",
            "canonical ubuntuserver 18_04-lts-gen2 18.04.202001210",
            "canonical ubuntuserver 18_04-lts-gen2 18.04.202004290",
            "canonical ubuntuserver 18_04-lts-gen2 18.04.202009220",
            # Mariner is supported after may 2023
            "microsoftcblmariner cbl-mariner cbl-mariner-2 2.20221122.01",
            "microsoftcblmariner cbl-mariner cbl-mariner-2 2.20230126.01",
            "microsoftcblmariner cbl-mariner cbl-mariner-2 2.20230303.02",
            "microsoftcblmariner cbl-mariner cbl-mariner-2-arm64 2.20230126.01",
        ]

        if image in known_bad_images:
            return True

        unsupported_versions: Dict[type, UnsupportedVersionInfo] = {
            Oracle: [{"major": 8, "minor": 5}],
            CentOs: [{"major": 8, "minor": 1}, {"major": 7, "minor": 4}],
            Redhat: [{"major": 8, "minor": 1}, {"major": 7, "minor": 4}],
        }

        version_info = node.os.information.version
        major_version = version_info.major
        minor_version = version_info.minor

        for distro, versions in unsupported_versions.items():
            if isinstance(node.os, distro):
                for version in versions:
                    if (
                        major_version == version["major"]
                        and minor_version < version["minor"]
                    ):
                        return True

        return False
