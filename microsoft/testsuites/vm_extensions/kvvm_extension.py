import os
import random
import time

from assertpy import assert_that
from azure.identity import DefaultAzureCredential
from azure.mgmt.authorization import AuthorizationManagementClient
from azure.mgmt.authorization.models import RoleAssignmentCreateParameters


from azure.mgmt.keyvault import KeyVaultManagementClient
from azure.mgmt.keyvault.models import (
    AccessPolicyEntry,
    Permissions,
    Sku,
    VaultCreateOrUpdateParameters,
    VaultProperties,
)

from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    node,
    simple_requirement,
)
from lisa.operating_system import FreeBSD
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    AzureNodeSchema,
    check_system_status,
    create_certificates,
    rotate_certificates,
    get_node_context,
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
        The following test case validates the Azure Key Vault Linux Extension while creating the following resources:
        A resource group
        A VM
        A Key Vault
        Two certificates in the Key Vault
        Retrieval of the certificate's secrets through SecretClient class from the Azure SDK.
        Installation of the Azure Key Vault Linux Extension on the VM.
        Rotation of the certificates (After KVVM Extension has been installed)
        All of the resources have been created by using the Azure SDK Python.
        """,
        priority=0,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_key_vault_extension(self, log: Logger, node: Node, result: TestResult) -> None:
        # Section for vault name and supported OS check
        vault_name = os.getenv("vault_name", f"python-keyvault-{random.randint(1, 100000):05}")
        vault_name_a = vault_name + "prp"
        if isinstance(node.os, FreeBSD):
            raise SkippedException(f"unsupported distro type: {type(node.os)}")

        # Section for environment setup
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        platform = environment.platform
        assert isinstance(platform, AzurePlatform)
        #VM attributes
        node_context = get_node_context(node)
        resource_group_name = node_context.resource_group_name
        node_capability = node.capability.get_extended_runbook(AzureNodeSchema, AZURE)
        location = node_capability.location
        #User's attributes
        user_tenant_id =  os.environ.get('tenant_id')
        user_object_id = os.environ.get('user_object_id')
        credential = DefaultAzureCredential(additionally_allowed_tenants=["*"])
        #We need to assign an identity to VM for later entry access policies for Key Vault
        compute_client = ComputeManagementClient(credential, platform.subscription_id)
        vm = compute_client.virtual_machines.get(resource_group_name, node_context.vm_name)
        object_id_vm = vm.identity.principal_id
        #Key Vault administrator role
        
        # Section for Key Vault properties and permissions
        keyvault_client = KeyVaultManagementClient(credential, platform.subscription_id)
        vault_properties = VaultProperties(
            tenant_id=user_tenant_id,
            sku=Sku(name="standard"),
            access_policies=[AccessPolicyEntry(
                #Permissions to create certificates
                tenant_id=user_tenant_id,
                object_id=user_object_id,
                permissions=Permissions(
                    keys=['all'],
                    secrets=['all'],
                    certificates=['all']
                )
            ),
                AccessPolicyEntry(
                    tenant_id=user_tenant_id,
                    object_id=object_id_vm, # Object ID of the VM
                    permissions=Permissions(
                        keys=['all'],          # Permissions for the VM
                        secrets=['all'],
                        certificates=['all']
                    )
                )
            ]            
        )
        #Creation of key vault
        parameters = VaultCreateOrUpdateParameters(location=location, properties=vault_properties)
        keyvault_poller = keyvault_client.vaults.begin_create_or_update(resource_group_name, vault_name_a, parameters)
        keyvault_result = keyvault_poller.result()
        log.info(f"Provisioned key vault {keyvault_result.name} in the {keyvault_result.location} region")

           # Assert that the name of the Key Vault matches the expected value
        assert_that(keyvault_result.name).described_as(
            "Expected the Key Vault name to match the given value"
        ).is_equal_to(vault_name_a)

        # Assert that the location of the Key Vault matches the expected value
        assert_that(keyvault_result.location).described_as(
            "Expected the Key Vault location to match the given value"
        ).is_equal_to(location)



        #Creation of two certificates, returns their secrets ID
        certificate1_secret_id, certificate2_secret_id = create_certificates(vault_url=keyvault_result.properties.vault_uri, credential=credential)
        log.info(f"Created certificates 'cert1' and 'cert2' in the key vault")
        log.info(f"Cert1: {certificate1_secret_id}")
        log.info(f"Cert2: {certificate2_secret_id}")
        # Assert that the first certificate's secret ID is not None, indicating successful creation
        assert_that(certificate1_secret_id).described_as(
            "Expected the first certificate's secret ID to be created successfully"
        ).is_not_none()

        # Assert that the second certificate's secret ID is not None, indicating successful creation
        assert_that(certificate2_secret_id).described_as(
            "Expected the second certificate's secret ID to be created successfully"
        ).is_not_none()

        # Section for extension details and installation
        extension_name = os.environ.get('extension_name')
        extension_publisher = os.environ.get('extension_publisher')
        extension_version = os.environ.get('extension_version')
        log.info(f"Installing extension: {extension_name}, publisher: {extension_publisher}, version: {extension_version}")
        settings = {
            "secretsManagementSettings": {
               "enableAutomaticUpgrade": True,
                "pollingIntervalInS": "10",
                "certificateStoreLocation": "/var/lib/waagent/Microsoft.Azure.KeyVault",
                "observedCertificates": [
                    certificate1_secret_id,
                    certificate2_secret_id
                ]
            }
        }
        extension = node.features[AzureExtension]
        result = extension.create_or_update(
            name=extension_name,
            publisher=extension_publisher,
            type_=extension_name,
            type_handler_version=extension_version,
            auto_upgrade_minor_version=True,
            settings=settings,
        )

                # Assert that the provisioning state of the extension installation succeeded
        assert_that(result["provisioning_state"]).described_as(
            "Expected the extension to succeed"
        ).is_equal_to("Succeeded")

     

        #Certificate rotation after AKV Extension installation
        rotate_certificates(self, log, vault_url=keyvault_result.properties.vault_uri, credential=credential, cert_name_to_rotate="Cert1")
        
        #Commands to VM to show certs/status of the extension
        check_system_status(node, log)


