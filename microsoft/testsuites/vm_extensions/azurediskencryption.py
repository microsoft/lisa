# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from assertpy import assert_that
from azure.mgmt.keyvault.models import AccessPolicyEntry, Permissions
from azure.mgmt.keyvault.models import Sku as KeyVaultSku  # type: ignore
from azure.mgmt.keyvault.models import VaultProperties
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
    CBLMariner,
    CentOs,
    Oracle,
    Redhat,
    Suse,
    Ubuntu,
)
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    AzureNodeSchema,
    create_keyvault,
    get_identity_id,
    get_tenant_id,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform, AzurePlatformSchema
from lisa.testsuite import TestResult

@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="Tests for the Azure Disk Encryption (ADE) extension",
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        supported_os=[Ubuntu, CBLMariner, CentOs, Oracle, Redhat, SLES, Suse],
    ),
)
class AzureDiskEncryption(TestSuite):
    @TestCaseMetadata(
        description="""
        Runs the ADE extension and verifies it executed on the
        remote machine.
        """,
        priority=1,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_azure_disk_encryption(
        self, log: Logger, node: Node, result: TestResult
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        platform = environment.platform
        assert isinstance(platform, AzurePlatform)
        runbook = platform.runbook.get_extended_runbook(AzurePlatformSchema)
        tenant_id = get_tenant_id(platform.credential)
        if tenant_id is None:
            raise ValueError("Environment variable 'tenant_id' is not set.")
        object_id = get_identity_id()
        if object_id is None:
            raise ValueError("Environment variable 'object_id' is not set.")

        # Create key vault
        node_capability = node.capability.get_extended_runbook(AzureNodeSchema, AZURE)
        location = node_capability.location
        vault_name = f"adelisakv-{location}"
        shared_resource_group = runbook.shared_resource_group_name

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
        keyvault_result = create_keyvault(
            platform=platform,
            resource_group_name=shared_resource_group,
            tenant_id=tenant_id,
            object_id=object_id,
            location=location,
            vault_name=vault_name,
            vault_properties=vault_properties,
        )

        # Check if KeyVault is successfully created before proceeding
        assert keyvault_result, f"Failed to create KeyVault with name: {vault_name}"

        # Run ADE Extension
        extension_name = "AzureDiskEncryptionForLinux"
        extension_publisher = "Microsoft.Azure.Security"
        extension_version = "1.4"
        settings = {
            "EncryptionOperation": "EnableEncryption",
            "KeyVaultURL": keyvault_result.properties.vault_uri,
            "KeyVaultResourceId": keyvault_result.id,
            "KeyEncryptionAlgorithm": "RSA-OAEP",
            "VolumeType": "ALL",
        }
        extension = node.features[AzureExtension]
        extension_result = extension.create_or_update(
            name=extension_name,
            publisher=extension_publisher,
            type_=extension_name,
            type_handler_version=extension_version,
            settings=settings,
        )

        log.debug(f"extension_result: {extension_result}")
        assert_that(extension_result["provisioning_state"]).described_as(
            "Expected the extension to succeed"
        ).is_equal_to("Succeeded")