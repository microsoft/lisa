# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import os
import random
import time
from typing import List

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.base_tools.service import Service
from lisa.operating_system import BSD
from lisa.sut_orchestrator.azure.common import (
    add_system_assign_identity,
    assign_access_policy_to_vm,
    check_certificate_existence,
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
from lisa.tools.ls import Ls
from lisa.util import LisaException


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="BVT for Azure Key Vault Extension",
    requirement=simple_requirement(unsupported_os=[]),
)
class AzureKeyVaultExtensionBvt(TestSuite):
    # Private method for checking system status
    def _check_system_status(self, node: Node, log: Logger) -> None:
        # Check the status of the akvvm_service service using the Service tool
        service = node.tools[Service]
        if service.is_service_running("akvvm_service.service"):
            log.info("akvvm_service is running")
        else:
            log.error("akvvm_service is not running")
            raise LisaException("akvvm_service is not running. Test case failed.")

        # List the contents of the directory
        ls = node.tools[Ls]
        directory_contents = ls.run(
            "/var/lib/waagent/Microsoft.Azure.KeyVault -la", sudo=True
        ).stdout
        log.info(f"Directory contents: {directory_contents}")

    @TestCaseMetadata(
        description="""
        The following test case validates the Azure Key Vault Linux
        * Extension while creating the following resources:
        * A Key Vault
        * Two certificates in the Key Vault
        * Retrieval of the certificate's secrets
        through SecretClient class from Azure SDK.
        * Installation of the Azure Key Vault Linux Extension on the VM.
        * Installation of the certs through AKV extension
        * Rotation of the certificates
        * Printing the cert after rotation from the VM
        * Deletion of the resources
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
        vault_name = f"kve-{time.strftime('%y%m%d%H%M%S')}-{random.randint(1, 1000):03}"

        # Section for environment setup
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        platform = environment.platform
        assert isinstance(platform, AzurePlatform)
        # VM attributes
        node_context = get_node_context(node)

        # User's attributes
        tenant_id = os.environ["AZURE_TENANT_ID"]
        if tenant_id is None:
            raise ValueError("Environment variable 'tenant_id' is not set.")
        object_id = os.environ["AZURE_CLIENT_ID"]
        if tenant_id is None:
            raise ValueError("Environment variable 'object_id' is not set.")
        assert object_id is not None

        # Object ID System assignment
        object_id_vm = add_system_assign_identity(
            platform=platform,
            resource_group_name=node_context.resource_group_name,
            vm_name=node_context.vm_name,
            location=node_context.location,
            log=log,
        )

        # Create Key Vault
        keyvault_result = create_keyvault(
            platform=platform,
            resource_group_name=node_context.resource_group_name,
            tenant_id=tenant_id,
            object_id=object_id,
            location=node_context.location,
            vault_name=vault_name,
        )
        # Acces policies for VM
        assign_access_policy_to_vm(
            platform=platform,
            resource_group_name=node_context.resource_group_name,
            tenant_id=tenant_id,
            object_id_vm=object_id_vm,
            vault_name=vault_name,
        )

        log.info(f"Created Key Vault {keyvault_result.properties.vault_uri}")

        certificates_secret_id: List[str] = []
        for cert_name in ["Cert1", "Cert2"]:
            certificate_secret_id = create_certificate(
                platform=platform,
                vault_url=keyvault_result.properties.vault_uri,
                log=log,
                cert_name=cert_name,
            )
            log.info(f"Certificates created. Cert ID: {certificate_secret_id}, ")
            assert_that(certificate_secret_id).described_as(
                "First certificate created successfully"
            ).is_not_none()
            certificates_secret_id.append(certificate_secret_id)

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
                    certificates_secret_id[0],
                    certificates_secret_id[1],
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
            platform=platform,
            cert_name_to_rotate="Cert1",
        )

        self._check_system_status(node, log)

        # Deleting the certificates after the test
        for cert_name in ["Cert2", "Cert1"]:
            delete_certificate(
                platform=platform,
                vault_url=keyvault_result.properties.vault_uri,
                cert_name=cert_name,
                log=log,
            )

            retries = 2
            for _ in range(retries):
                certificate_exists = check_certificate_existence(
                    vault_url=keyvault_result.properties.vault_uri,
                    cert_name=cert_name,
                    log=log,
                    platform=platform,
                )
                if not certificate_exists:
                    break
                time.sleep(5)  # wait for 5 seconds before retrying

            assert_that(certificate_exists).is_false()
        # Deleting key vault
        delete_keyvault(
            platform=platform,
            resource_group_name=node_context.resource_group_name,
            vault_name=vault_name,
            log=log,
        )

        assert_that(keyvault_result.properties.vault_uri).does_not_exist

        # Delete VM Extension
        extension.delete("KeyVaultForLinux")

        assert_that(extension.check_exist("KeyVaultForLinux")).described_as(
            "Found the VM Extension still exists on the VM after deletion"
        ).is_false()
