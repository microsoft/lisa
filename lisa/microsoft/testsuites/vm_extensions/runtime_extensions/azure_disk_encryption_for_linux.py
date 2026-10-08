# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import string
from typing import Any, Dict

import requests
from azure.mgmt.keyvault.models import AccessPolicyEntry, Permissions
from azure.mgmt.keyvault.models import Sku as KeyVaultSku
from azure.mgmt.keyvault.models import VaultProperties
from microsoft.testsuites.vm_extensions.vm_extension_base import VmExtensionTestBase

from lisa import Logger, Node, TestCaseMetadata, TestSuiteMetadata, simple_requirement
from lisa.environment import Environment
from lisa.features.security_profile import CvmDisabled
from lisa.operating_system import (
    BSD,
    CBLMariner,
    CentOs,
    Oracle,
    Redhat,
    Ubuntu,
    Windows,
)
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    create_keyvault,
    get_identity_id,
    get_matching_key_vault_name,
    get_node_context,
    get_tenant_id,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform, AzurePlatformSchema
from lisa.tools import Lscpu
from lisa.tools.lscpu import CpuArchitecture
from lisa.util import (
    LisaException,
    SkippedException,
    UnsupportedCpuArchitectureException,
    generate_random_chars,
)

# ADE encryption on Linux requires at least 7 GiB of memory on the target VM
# (Azure Disk Encryption prerequisites); request 8 GiB so environment
# selection picks a VM size that can run the handler's enable path.
MIN_REQUIRED_MEMORY_MB = 8 * 1024


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    This test suite validates the Azure Disk Encryption VM extension for Linux
    (Microsoft.Azure.Security.AzureDiskEncryptionForLinux).

    Coverage starts with boot validation: provision the key vault the handler
    needs, install the extension with the supported EnableEncryption settings,
    confirm provisioning succeeds, confirm the requested version was installed,
    and confirm the VM is still reachable over SSH.
    """,
    tags=["VM_Extension", "AzureDiskEncryptionForLinux"],
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        unsupported_os=[BSD, Windows],
    ),
)
class AzureDiskEncryptionForLinuxTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.Azure.Security"
    EXTENSION_TYPE = "AzureDiskEncryptionForLinux"
    EXTENSION_KEY = "azure_disk_encryption_for_linux"
    # Encryption continues after extension provisioning reports success.
    # Removing the handler mid-operation is unsafe, so leave cleanup to
    # resource-group teardown.
    SUPPORTS_DELETE = False

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs.pop("node")
        node_arch = node.tools[Lscpu].get_architecture()
        if node_arch != CpuArchitecture.X64:
            raise SkippedException(
                UnsupportedCpuArchitectureException(arch=str(node_arch.value))
            )

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        # Encryption continues in the background, so this environment must not
        # be reused by another test.
        node: Node = kwargs.pop("node")
        node.mark_dirty()

    @TestCaseMetadata(
        description="""
        Basic boot validation for the Azure Disk Encryption extension for Linux.

        Provisions or reuses an ADE-enabled key vault, then installs the
        explicitly requested candidate version using the same EnableEncryption
        settings as verify_azure_disk_encryption_provisioned. The case verifies
        that extension provisioning succeeds and does not wait for the OS disk
        to report its final Encrypted status.

        Encryption continues after extension provisioning, so the node is
        marked dirty and the extension is left for resource-group teardown.

        The candidate version is read from the 'extension_version' or
        'azure_disk_encryption_for_linux_version' runbook variable.
        """,
        priority=5,
        requirement=simple_requirement(
            min_memory_mb=MIN_REQUIRED_MEMORY_MB,
            supported_os=[Redhat, CentOs, Oracle, Ubuntu, CBLMariner],
            supported_features=[AzureExtension, CvmDisabled()],
            supported_platform_type=[AZURE],
        ),
        tags=["microsoft.azure.security.azurediskencryptionforlinux"],
        maturity="preview",
    )
    def microsoft_azure_security_azurediskencryptionforlinux_boot_validation_test(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        variables: Dict[str, Any],
    ) -> None:
        platform = environment.platform
        assert isinstance(platform, AzurePlatform)

        self._boot_validation(
            node=node,
            log=log,
            variables=variables,
            settings=self._build_settings(node=node, platform=platform, log=log),
        )

    def _build_settings(
        self, node: Node, platform: AzurePlatform, log: Logger
    ) -> Dict[str, Any]:
        runbook = platform.runbook.get_extended_runbook(AzurePlatformSchema)
        shared_resource_group = runbook.shared_resource_group_name
        location = get_node_context(node).location

        tenant_id = get_tenant_id(platform.credential)
        if tenant_id is None:
            raise LisaException("Cannot resolve the tenant id of the subscription.")

        object_id = self._resolve_runner_object_id(platform, runbook, log)
        if not object_id:
            raise LisaException("Cannot resolve the object id of the test runner.")

        vault_name = get_matching_key_vault_name(
            platform, location, shared_resource_group, r"lisa-ade-\w{5}"
        )
        if not vault_name:
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
        keyvault = create_keyvault(
            platform=platform,
            location=location,
            vault_name=vault_name,
            resource_group_name=shared_resource_group,
            vault_properties=vault_properties,
        )
        if not keyvault:
            raise LisaException(f"Failed to create key vault '{vault_name}'.")
        log.info(f"Using key vault {keyvault.properties.vault_uri}")

        return {
            "EncryptionOperation": "EnableEncryption",
            "KeyVaultURL": keyvault.properties.vault_uri,
            "KeyVaultResourceId": keyvault.id,
            "KeyEncryptionAlgorithm": "RSA-OAEP",
            "VolumeType": "Os",
        }

    def _resolve_runner_object_id(
        self, platform: AzurePlatform, runbook: Any, log: Logger
    ) -> str:
        """
        Resolve the object id to grant on the key vault access policy.

        The production path is get_identity_id. It resolves the service
        principal when one is configured, otherwise the signed-in user via
        Graph /me. When the runner is itself an Azure VM, it instead resolves
        that VM's managed identity -- which fails when the runner VM lives in a
        different subscription than the one under test. In that case fall back
        to the signed-in user via Graph /me using LISA's own credential, so the
        test still deploys and runs against its own VM.
        """
        try:
            object_id = get_identity_id(
                platform=platform,
                application_id=runbook.service_principal_client_id,
            )
            if object_id:
                return str(object_id)
        except Exception as e:
            log.debug(f"get_identity_id failed, falling back to signed-in user: {e}")

        token = platform.credential.get_token(
            "https://graph.microsoft.com/.default"
        ).token
        response = requests.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        response.raise_for_status()
        return str(response.json()["id"])
