# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import json
import string
import time
from typing import Any, Dict, List, Optional

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
from lisa.tools import Lscpu
from lisa.tools.lscpu import CpuArchitecture
from lisa.util import (
    SkippedException,
    UnsupportedCpuArchitectureException,
    UnsupportedDistroException,
    generate_random_chars,
)

# Allow up to 3.5 hours total: 3 hours of initial polling for encryption
# completion plus up to ~30 minutes of extended polling when the extension
# is still reporting "EncryptionInProgress" at the 3-hour mark.
TIME_LIMIT = int(3600 * 3.5)
MIN_REQUIRED_MEMORY_MB = 8 * 1024

# Define a type alias for readability
UnsupportedVersionInfo = List[Dict[str, int]]


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="Tests for the Azure Disk Encryption (ADE) extension",
    tags=["VM_Extension"],
)
class AzureDiskEncryption(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        node_arch = node.tools[Lscpu].get_architecture()
        # ADE only supports x64 architecture. See supported VM configurations at:
        # https://learn.microsoft.com/en-us/azure/virtual-machines/linux/disk-encryption-overview#supported-vms-and-operating-systems
        if node_arch != CpuArchitecture.X64:
            raise SkippedException(
                UnsupportedCpuArchitectureException(arch=str(node_arch.value))
            )
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
        # Initial polling: up to 2 hours, checking every 5 minutes (24 retries).
        # If the extension is still reporting "EncryptionInProgress" at the
        # 2-hour mark, extend polling by an additional 1 hour (12 more retries)
        # to accommodate slow encryption on older distros / VM SKUs where
        # encryption legitimately takes longer than 2 hours.
        initial_retries = 24
        extended_retries = 12
        retry_interval = 300  # 5 minutes in seconds
        os_status = None
        extension = node.features[AzureExtension]
        extension_status = extension.get(name="AzureDiskEncryptionForLinux")
        instance_view = extension_status.instance_view
        log.debug(f"Extension status: {extension_status}")
        log.debug(f"Instance view: {instance_view}")

        def _poll_os_status() -> Optional[str]:
            latest_status: Optional[str] = None
            current = extension.get(name="AzureDiskEncryptionForLinux")
            for substatus in current.instance_view.substatuses:
                log.debug(f"Substatus: {substatus}")
                try:
                    message_json = json.loads(substatus.message)
                    candidate = message_json.get("os")
                    if candidate:
                        latest_status = candidate
                except json.JSONDecodeError:
                    log.error(f"Failed to parse message content: {substatus.message}")
            return latest_status

        # Phase 1: initial 2-hour poll for "Encrypted".
        for i in range(initial_retries):
            os_status = _poll_os_status()
            if os_status == "Encrypted":
                log.debug("The 'os' status is 'Encrypted'")
                break

            if i < initial_retries - 1:
                log.debug(
                    f"Sleeping for {retry_interval} seconds before checking again"
                )
                log.debug(f"Initial retry #{i + 1} of {initial_retries}")
                time.sleep(retry_interval)

        # Phase 2: if encryption is still progressing after the initial window,
        # extend polling by up to 1 more hour. This handles slow-encryption
        # scenarios (older distros, older VM SKUs) where the extension is
        # healthy but has not yet reported "Encrypted".
        if os_status != "Encrypted" and os_status == "EncryptionInProgress":
            log.info(
                "Initial 2-hour window elapsed with status 'EncryptionInProgress'. "
                "Extending polling by up to 1 more hour for 'Encrypted'."
            )
            for j in range(extended_retries):
                log.debug(
                    f"Sleeping for {retry_interval} seconds before checking again"
                )
                log.debug(f"Extended retry #{j + 1} of {extended_retries}")
                time.sleep(retry_interval)
                os_status = _poll_os_status()
                if os_status == "Encrypted":
                    log.debug("The 'os' status is 'Encrypted' after extended polling")
                    break

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
