# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
import random

from assertpy import assert_that
from azure.identity import DefaultAzureCredential  # type: ignore
from azure.mgmt.compute import ComputeManagementClient  # type: ignore
from azure.mgmt.keyvault import KeyVaultManagementClient  # type: ignore
from azure.mgmt.keyvault.models import (  # type: ignore
    AccessPolicyEntry,
    Permissions,
    Sku,
    VaultCreateOrUpdateParameters,
    VaultProperties,
)

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import FreeBSD
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    AzureNodeSchema,
    check_system_status,
    create_certificates,
    get_node_context,
    rotate_certificates,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.testsuite import TestResult
from lisa.util import SkippedException


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="BVT for Azure Key Vault Extension",
    requirement=simple_requirement(unsupported_os=[]),
)
class AzureKeyVaultExtensionBvt(TestSuite):
    @TestCaseMetadata(
        description="""
        The following test case validates the Azure Key Vault Linux
        Extension while creating the following resources:
        A resource group
        A VM
        A Key Vault
        Two certificates in the Key Vault
        Retrieval of the certificate's secrets
        through SecretClient class from Azure SDK.
        Installation of the Azure Key Vault Linux Extension on the VM.
        Rotation of the certificates (After KVVM Extension has been installed)
        All of the resources have been created by using the Azure SDK Python.
        """,
        priority=1,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_key_vault_extension(
        self, log: Logger, node: Node, result: TestResult
    ) -> None:
        # Section for vault name and supported OS check
        vault_name = os.getenv(
            "vault_name", f"python-keyvault-{random.randint(1, 100000):05}"
        )
        vault_name_a = vault_name + "prp"
        if isinstance(node.os, FreeBSD):
            raise SkippedException(f"unsupported distro type: {type(node.os)}")

        # Section for environment setup
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        platform = environment.platform
        assert isinstance(platform, AzurePlatform)
        # VM attributes
        node_context = get_node_context(node)
        resource_group_name = node_context.resource_group_name
        node_capability = node.capability.get_extended_runbook(AzureNodeSchema, AZURE)
        location = node_capability.location

        # User's attributes
        user_tenant_id = os.environ.get("tenant_id")
        if user_tenant_id is None:
            raise ValueError("Environment variable 'tenant_id' is not set.")
        user_object_id = os.environ.get("user_object_id")
        if user_tenant_id is None:
            raise ValueError("Environment variable 'user_object_id' is not set.")
        assert user_object_id is not None
        credential = DefaultAzureCredential(additionally_allowed_tenants=["*"])

        # Identity assignment
        compute_client = ComputeManagementClient(credential, platform.subscription_id)
        vm = compute_client.virtual_machines.get(
            resource_group_name, node_context.vm_name
        )
        object_id_vm = vm.identity.principal_id
        if object_id_vm is None:
            raise ValueError("object_id_vm is not set.")

        # Key Vault properties
        keyvault_client = KeyVaultManagementClient(credential, platform.subscription_id)
        vault_properties = VaultProperties(
            tenant_id=user_tenant_id,
            sku=Sku(name="standard"),
            access_policies=[
                AccessPolicyEntry(
                    tenant_id=user_tenant_id,
                    object_id=user_object_id,
                    permissions=Permissions(
                        keys=["all"], secrets=["all"], certificates=["all"]
                    ),
                ),
                AccessPolicyEntry(
                    tenant_id=user_tenant_id,
                    object_id=object_id_vm,
                    permissions=Permissions(
                        keys=["all"], secrets=["all"], certificates=["all"]
                    ),
                ),
            ],
        )

        # Create Key Vault
        parameters = VaultCreateOrUpdateParameters(
            location=location, properties=vault_properties
        )
        keyvault_poller = keyvault_client.vaults.begin_create_or_update(
            resource_group_name, vault_name_a, parameters
        )
        keyvault_result = keyvault_poller.result()

        # Assertions and logging
        log.info(
            f"Provisioned vault {keyvault_result.name} "
            f"in {keyvault_result.location} region"
        )
        assert_that(keyvault_result.name).described_as(
            "Expected the Key Vault name to match the given value"
        ).is_equal_to(vault_name_a)
        assert_that(keyvault_result.location).described_as(
            "Expected the Key Vault location to match the given value"
        ).is_equal_to(location)

        # Certificates
        log.info(
            "About to call create_certificates with vault_url: %s",
            keyvault_result.properties.vault_uri,
        )
        certificate1_secret_id, certificate2_secret_id = create_certificates(
            vault_url=keyvault_result.properties.vault_uri,
            credential=credential,
            log=log,
        )
        log.info(
            "Certificates created. Cert1 ID: %s, Cert2 ID: %s",
            certificate1_secret_id,
            certificate2_secret_id,
        )
        assert_that(certificate1_secret_id).described_as(
            "First certificate created successfully"
        ).is_not_none()
        assert_that(certificate2_secret_id).described_as(
            "Second certificate created successfully"
        ).is_not_none()

        # Extension
        extension_name = "KeyVaultForLinux"
        extension_publisher = "Microsoft.Azure.KeyVault"
        extension_version = "2.0"
        settings = {
            "secretsManagementSettings": {
                "autoUpgradeMinorVersion": True,
                "enableAutomaticUpgrade": True,
                "pollingIntervalInS": "360",
                "certificateStoreLocation": "/var/lib/waagent/Microsoft.Azure.KeyVault",
                "observedCertificates": [
                    certificate1_secret_id,
                    certificate2_secret_id,
                ],
            }
        }
        extension = node.features[AzureExtension]
        extension_result = extension.create_or_update(
            name=extension_name,
            publisher=extension_publisher,
            type_=extension_name,
            type_handler_version=extension_version,
            auto_upgrade_minor_version=True,
            enable_automatic_upgrade=True,
            settings=settings,
        )
        assert_that(extension_result["provisioning_state"]).described_as(
            "Expected the extension to succeed"
        ).is_equal_to("Succeeded")

        # Rotate certificates
        rotate_certificates(
            log,
            vault_url=keyvault_result.properties.vault_uri,
            credential=credential,
            cert_name_to_rotate="Cert1",
        )
        assert True, "Cert1 has been rotated."
        check_system_status(node, log)
