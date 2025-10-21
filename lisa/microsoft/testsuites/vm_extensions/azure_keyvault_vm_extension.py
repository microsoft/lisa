# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import string
from typing import Any, List

from assertpy import assert_that
from azure.mgmt.keyvault.models import AccessPolicyEntry, Permissions
from azure.mgmt.keyvault.models import Sku as KeyVaultSku
from azure.mgmt.keyvault.models import VaultProperties

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.base_tools.service import Service
from lisa.operating_system import BSD, CBLMariner, Ubuntu
from lisa.sut_orchestrator.azure.common import (
    add_system_assign_identity,
    assign_access_policy,
    check_certificate_existence,
    create_certificate,
    create_keyvault,
    delete_certificate,
    get_identity_id,
    get_node_context,
    get_tenant_id,
    rotate_certificate,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform, AzurePlatformSchema
from lisa.testsuite import TestResult
from lisa.tools.ls import Ls
from lisa.tools.whoami import Whoami
from lisa.util import LisaException, SkippedException, generate_random_chars


def _check_system_status(node: Node, log: Logger) -> None:
    # Check the status of the akvvm_service service using the Service tool
    service = node.tools[Service]
    if service.is_service_running("akvvm_service.service"):
        log.info("akvvm_service is running")
    else:
        log.info("akvvm_service is not running")
        raise LisaException("akvvm_service is not running. Test case failed.")

    # List the contents of the directory
    ls = node.tools[Ls]
    directory_contents = ls.run("/var/lib/waagent -la", sudo=True).stdout
    log.info(f"Directory contents: {directory_contents}")

    # check certs files
    for path in ["a", "b"]:
        file_path = f"/var/lib/waagent/{path}/symbolink{path}"
        message = f"File {file_path} was not created on the test machine"

        ls.run(
            file_path,
            expected_exit_code=0,
            expected_exit_code_failure_message=message,
        )


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="BVT for Azure Key Vault Extension",
    requirement=simple_requirement(unsupported_os=[]),
)
class AzureKeyVaultExtensionBvt(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        if not self._is_supported_linux_distro(node):
            raise SkippedException(
                f"{str(node.os.information.full_version)} is not supported."
            )

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
        priority=1,
        requirement=simple_requirement(
            supported_features=[AzureExtension], unsupported_os=[BSD]
        ),
    )
    def verify_key_vault_extension(
        self, log: Logger, node: Node, result: TestResult
    ) -> None:
        # Section for environment setup
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        platform = environment.platform
        assert isinstance(platform, AzurePlatform)
        runbook = platform.runbook.get_extended_runbook(AzurePlatformSchema)
        resource_group_name = runbook.shared_resource_group_name
        application_id = runbook.service_principal_client_id
        node_context = get_node_context(node)

        # A vault's name must be between 3-24 alphanumeric characters.
        vault_name = (
            f"lisa-kv{platform.subscription_id[-6:]}{node_context.location[:11]}"
        )
        tenant_id = get_tenant_id(platform.credential)
        if tenant_id is None:
            raise ValueError("Environment variable 'tenant_id' is not set.")
        object_id = get_identity_id(platform=platform, application_id=application_id)
        if object_id is None:
            raise ValueError("Environment variable 'object_id' is not set.")

        # Object ID System assignment
        object_id_vm = add_system_assign_identity(
            platform=platform,
            resource_group_name=node_context.resource_group_name,
            vm_name=node_context.vm_name,
            location=node_context.location,
            log=log,
        )
        vault_properties = VaultProperties(
            tenant_id=tenant_id,
            sku=KeyVaultSku(name="standard"),
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

        # Create Key Vault
        keyvault_result = create_keyvault(
            platform=platform,
            location=node_context.location,
            vault_name=vault_name,
            resource_group_name=resource_group_name,
            vault_properties=vault_properties,
        )

        # Check if KeyVault is successfully created before proceeding
        assert keyvault_result, f"Failed to create KeyVault with name: {vault_name}"

        # Access policies for VM
        assign_access_policy(
            platform=platform,
            resource_group_name=resource_group_name,
            tenant_id=tenant_id,
            object_id=object_id_vm,
            vault_name=vault_name,
        )

        log.info(f"Created Key Vault {keyvault_result.properties.vault_uri}")

        certificates_secret_id: List[str] = []
        cert_names = [
            generate_random_chars(string.ascii_lowercase + string.digits, 6)
            for _ in range(2)
        ]
        for cert_name in cert_names:
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

        current_user = node.tools[Whoami].get_username()

        # Extension
        extension_name = "KeyVaultForLinux"
        extension_publisher = "Microsoft.Azure.KeyVault"
        extension_version = "3.0"
        settings = {
            "secretsManagementSettings": {
                "autoUpgradeMinorVersion": True,
                "enableAutomaticUpgrade": True,
                "pollingIntervalInS": "360",
                "certificateStoreLocation": "/var/lib/waagent/Microsoft.Azure.KeyVault",
                "observedCertificates": [
                    {
                        "url": certificates_secret_id[0],
                        "certificateStoreLocation": "/var/lib/waagent/a",
                        "customSymbolicLinkName": "symbolinka",
                        "acls": [{"user": current_user}],
                    },
                    {
                        "url": certificates_secret_id[1],
                        "certificateStoreLocation": "/var/lib/waagent/b",
                        "customSymbolicLinkName": "symbolinkb",
                        "acls": [{"user": current_user}],
                    },
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
        # Example: "https://example.vault.azure.net/secrets/Cert-123"
        # Expected match: "Cert-123"
        match = re.search(r"/(?P<certificate_name>[^/]+)$", certificates_secret_id[0])
        if match:
            cert_name = match.group("certificate_name")
        else:
            raise LisaException(
                f"Failed to extract certificate name from {certificates_secret_id[0]}"
            )
        rotate_certificate(
            platform=platform,
            vault_url=keyvault_result.properties.vault_uri,
            cert_name=cert_name,
            log=log,
        )

        _check_system_status(node, log)

        for cert_secret_id in certificates_secret_id:
            # Example: "https://example.vault.azure.net/secrets/Cert-123"
            # Expected match for 'certificate_name': "Cert-123"
            match = re.search(r"/(?P<certificate_name>[^/]+)$", cert_secret_id)
            if match:
                cert_name = match.group("certificate_name")
            else:
                raise LisaException(
                    f"Failed to extract certificate name from {cert_secret_id}"
                )
            delete_certificate(
                platform=platform,
                vault_url=keyvault_result.properties.vault_uri,
                cert_name=cert_name,
                log=log,
            )

            certificate_exists = check_certificate_existence(
                log=log,
                platform=platform,
                vault_url=keyvault_result.properties.vault_uri,
                cert_name=cert_name,
            )

            assert_that(certificate_exists).described_as(
                f"The certificate '{cert_name}' was not deleted after 10 attempts."
            ).is_false()

        # Delete VM Extension
        extension.delete("KeyVaultForLinux")

        assert_that(extension.check_exist("KeyVaultForLinux")).described_as(
            "Found the VM Extension still exists on the VM after deletion"
        ).is_false()

    def _is_supported_linux_distro(self, node: Node) -> bool:
        supported_major_versions = {
            Ubuntu: [20, 22],
            CBLMariner: [2],
        }

        for distro in supported_major_versions:
            if type(node.os) is distro:
                version_list = supported_major_versions.get(distro)
                if (
                    version_list is not None
                    and node.os.information.version.major in version_list
                ):
                    return True
                else:
                    return False
        return False
