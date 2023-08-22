# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import json
import time

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
from lisa.operating_system import SLES, CBLMariner, CentOs, Oracle, Redhat, Suse, Ubuntu
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    AzureNodeSchema,
    create_keyvault,
    get_sp_object_id,
    get_tenant_id,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform, AzurePlatformSchema
from lisa.testsuite import TestResult


def _enable_ade_extension(node: Node, log: Logger, result: TestResult) -> any:
    environment = result.environment
    assert environment, "fail to get environment from testresult"
    platform = environment.platform
    assert isinstance(platform, AzurePlatform)
    runbook = platform.runbook.get_extended_runbook(AzurePlatformSchema)
    tenant_id = get_tenant_id(platform.credential)
    if tenant_id is None:
        raise ValueError("Environment variable 'tenant_id' is not set.")
    object_id = get_sp_object_id(runbook.service_principal_client_id)
    log.debug(f"Object ID: {object_id}")
    log.debug(f"Runbook: {runbook}")
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
        Runs the ADE extension and verifies it enabled and fully encrypted the remote machine successfully.
        """,
        priority=1,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_azure_disk_encryption_enabled(
        self, log: Logger, node: Node, result: TestResult
    ) -> None:
        extension_result = _enable_ade_extension(node, log, result)
        assert_that(extension_result["provisioning_state"]).described_as(
            "Expected the extension to succeed"
        ).is_equal_to("Succeeded")

        # Get VM Extension status
        # Maximum time to check is 2 hours, which is 120 minutes.
        # We're checking every 5 minutes, so the loop will run 120/5 = 24 times.
        max_retries = 24
        retry_interval = 300  # 5 minutes in seconds
        os_status = None

        for i in range(max_retries):
            extension = node.features[AzureExtension]
            extension_status = extension.get(name="AzureDiskEncryptionForLinux")
            instance_view = extension_status.instance_view
            substatuses = instance_view.substatuses
            log.debug(f"Extension status: {extension_status}")
            log.debug(f"Instance view: {instance_view}")
            log.debug(f"Substatuses: {substatuses}")

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
                time.sleep(retry_interval)
                log.debug(
                    f"Sleeping for {retry_interval} seconds before checking again"
                )
                log.debug(f"Retry #{i+1} of {max_retries}")

        assert_that(os_status).described_as(
            "Expected the OS status to be 'Encrypted'"
        ).is_equal_to("Encrypted")

    @TestCaseMetadata(
        description="""
        Runs the ADE extension and verifies the extension provisioned successfully on the remote machine.
        """,
        priority=0,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_azure_disk_encryption_provisioned(
        self, log: Logger, node: Node, result: TestResult
    ) -> None:
        extension_result = _enable_ade_extension(node, log, result)

        assert_that(extension_result["provisioning_state"]).described_as(
            "Expected the extension to succeed"
        ).is_equal_to("Succeeded")
