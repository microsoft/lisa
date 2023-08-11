# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import os
import random

from assertpy import assert_that
from azure.identity import DefaultAzureCredential

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import BSD
from lisa.sut_orchestrator.azure.common import (
    add_system_assign_identity,
    check_certificate_existence,
    check_system_status,
    create_certificate,
    create_keyvault,
    delete_certificate,
    delete_keyvault,
    get_node_context,
    rotate_certificates,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.testsuite import TestResult


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
        priority=0,
        requirement=simple_requirement(
            supported_features=[AzureExtension], unsupported_os=[BSD]
        ),
    )
    def verify_key_vault_extension(
        self, log: Logger, node: Node, result: TestResult
    ) -> None:
        # Section for vault name and supported OS check
        vault_name_a = f"python-keyvault-{random.randint(1, 100000):05}prp"

        # Section for environment setup
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        platform = environment.platform
        assert isinstance(platform, AzurePlatform)
        # VM attributes
        node_context = get_node_context(node)

        # User's attributes
        user_tenant_id = os.environ.get("tenant_id")
        if user_tenant_id is None:
            raise ValueError("Environment variable 'tenant_id' is not set.")
        user_object_id = os.environ.get("user_object_id")
        if user_tenant_id is None:
            raise ValueError("Environment variable 'user_object_id' is not set.")
        assert user_object_id is not None
        credential = DefaultAzureCredential(additionally_allowed_tenants=["*"])

        # Object ID System assignment
        object_id_vm = add_system_assign_identity(
            credential=credential,
            subscription_id=node_context.subscription_id,
            resource_group_name=node_context.resource_group_name,
            vm_name=node_context.vm_name,
            location=node_context.location,
            log=log,
        )

        # Create Key Vault
        keyvault_result = create_keyvault(
            credential,
            platform.subscription_id,
            user_tenant_id,
            user_object_id,
            object_id_vm,
            node_context.location,
            node_context.resource_group_name,
            vault_name_a,
        )

        log.info(f"Created Key Vault {keyvault_result.properties.vault_uri}")

        # Certificates
        log.info(
            "About to call create_certificates with vault_url: "
            f"{keyvault_result.properties.vault_uri}"
        )
        certificate1_secret_id = create_certificate(
            vault_url=keyvault_result.properties.vault_uri,
            credential=credential,
            log=log,
            cert_name="Cert1",
        )
        certificate2_secret_id = create_certificate(
            vault_url=keyvault_result.properties.vault_uri,
            credential=credential,
            log=log,
            cert_name="Cert2",
        )
        log.info(
            f"Certificates created. Cert1 ID: {certificate1_secret_id}, "
            f"Cert2 ID: {certificate2_secret_id}"
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
        check_system_status(node, log)

        # Deleting the certificates after the test
        delete_certificate(
            vault_url=keyvault_result.properties.vault_uri,
            credential=credential,
            cert_name="Cert1",
            log=log,
        )
        assert_that(
            check_certificate_existence(
                vault_url=keyvault_result.properties.vault_uri,
                cert_name="Cert1",
                credential=credential,
                log=log,
            )
        ).is_false

        delete_certificate(
            vault_url=keyvault_result.properties.vault_uri,
            credential=credential,
            cert_name="Cert2",
            log=log,
        )

        assert_that(
            check_certificate_existence(
                vault_url=keyvault_result.properties.vault_uri,
                cert_name="Cert1",
                credential=credential,
                log=log,
            )
        ).is_false
        # Deleting key vault
        delete_keyvault(
            credential=credential,
            subscription_id=platform.subscription_id,
            resource_group_name=node_context.resource_group_name,
            vault_name_a=vault_name_a,
            log=log,
        )

        assert_that(keyvault_result.properties.vault_uri).does_not_exist

        # Delete VM Extension
        extension.delete("KeyVaultForLinux")

        assert_that(extension.check_exist("KeyVaultForLinux")).described_as(
            "Found the VM Extension still exists on the VM after deletion"
        ).is_false()
