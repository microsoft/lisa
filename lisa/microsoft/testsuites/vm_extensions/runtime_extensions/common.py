# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict, Optional

from assertpy import assert_that
from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobType

from lisa import Logger, Node
from lisa.environment import Environment
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    AZURE_SHARED_RG_NAME,
    AzureNodeSchema,
    generate_user_delegation_sas_token,
    get_or_create_storage_container,
    get_storage_account_name,
    get_storage_credential,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.sut_orchestrator.azure.tools import Waagent
from lisa.util import LisaException, SkippedException, parse_version


def create_and_verify_vmaccess_extension_run(
    node: Node,
    settings: Optional[Dict[str, Any]] = None,
    protected_settings: Optional[Dict[str, Any]] = None,
) -> None:
    extension = node.features[AzureExtension]
    result = extension.create_or_update(
        name="VMAccess",
        publisher="Microsoft.OSTCExtensions",
        type_="VMAccessForLinux",
        type_handler_version="1.5",
        auto_upgrade_minor_version=True,
        settings=settings or {},
        protected_settings=protected_settings or {},
    )

    assert_that(result["provisioning_state"]).described_as(
        "Expected the extension to succeed"
    ).is_equal_to("Succeeded")


def run_extension_boot_validation(
    node: Node,
    log: Logger,
    variables: Dict[str, Any],
    default_publisher: str,
    default_extension_type: str,
    settings: Dict[str, Any],
    cleanup: bool = True,
) -> None:
    """
    Shared boot-validation flow for VM extensions.

    Installs the extension with the provided inline settings, asserts that
    provisioning succeeds, and optionally removes it. Extensions managed by the
    Compute Resource Provider (e.g. RunCommand v2 / RunCommandHandlerLinux)
    cannot be deleted with a normal 'Delete VM Extension' operation, so callers
    pass cleanup=False for those and rely on resource group teardown instead.

    The publisher and type are read from the runbook variables
    extension_publisher and extension_type, defaulting to the values passed by
    the caller. The extension_version runbook variable is required and must be a
    'Major.Minor' or 'Major.Minor.Patch' value; the test is skipped if it is not
    set or is malformed. The deployed extension is named
    '<publisher>_<extension_type>_boot_validation_test'.
    """
    publisher: str = str(
        variables.get("extension_publisher", default_publisher)
    ).strip()
    extension_type: str = str(
        variables.get("extension_type", default_extension_type)
    ).strip()
    version: str = str(variables.get("extension_version", "")).strip()

    if not version:
        raise SkippedException(
            "Required runbook variable 'extension_version' is missing or "
            "empty. Please set it in the runbook before running this test case."
        )

    extension_name = f"{publisher}_{extension_type}_boot_validation_test"

    extension = node.features[AzureExtension]

    # Skip if extension_version is not a valid 'Major.Minor' or
    # 'Major.Minor.Patch' value. Reuse AzureExtension's validator, which raises
    # LisaException on a malformed version, and turn that into a skip. Use the
    # normalized 'Major.Minor' value for installation (Azure installs by
    # Major.Minor even when a patch version is supplied).
    try:
        install_version, _ = extension.normalize_type_handler_version(version)
    except LisaException:
        raise SkippedException(
            f"Runbook variable 'extension_version'='{version}' is not a valid "
            "'Major.Minor' or 'Major.Minor.Patch' version. Please set a valid "
            "version in the runbook before running this test case."
        )

    if cleanup:
        extension.delete(name=extension_name, ignore_not_found=True)

    try:
        log.info(f"Installing extension '{extension_name}'...")
        result = extension.create_or_update(
            name=extension_name,
            publisher=publisher,
            type_=extension_type,
            type_handler_version=install_version,
            auto_upgrade_minor_version=True,
            settings=settings,
        )

        assert_that(result["provisioning_state"]).described_as(
            "Expected the extension to succeed"
        ).is_equal_to("Succeeded")
    finally:
        if cleanup:
            extension.delete(name=extension_name, ignore_not_found=True)


def execute_command(file_name: str, expected_exit_code: int, node: Node) -> None:
    command = f"ls '{file_name}'"
    if expected_exit_code == 0:
        failure_message = f"File {file_name} was not created on the test machine"
    else:
        failure_message = (
            f"File {file_name} downloaded on test machine though it should not have"
        )

    node.execute(
        command,
        shell=True,
        expected_exit_code=expected_exit_code,
        expected_exit_code_failure_message=failure_message,
    )


def check_waagent_version_supported(node: Node) -> None:
    waagent = node.tools[Waagent]
    waagent_version = waagent.get_version()
    result = parse_version(waagent_version).compare("2.4.0")
    if result < 0:
        waagent_auto_update_enabled = waagent.is_autoupdate_enabled()
        if not waagent_auto_update_enabled:
            raise SkippedException(
                f"Node with Windows Azure Linux Agent version {waagent_version}"
                " is lower than 2.4.0 and doesn't have multiconfig support."
            )


def retrieve_storage_blob_url(
    node: Node,
    environment: Environment,
    container_name: str = "",
    blob_name: str = "",
    test_file: str = "",
    is_sas: bool = False,
    script: str = "",
    blob_type: BlobType = BlobType.BLOCKBLOB,
) -> Any:
    platform = environment.platform
    assert isinstance(platform, AzurePlatform)

    subscription_id = platform.subscription_id
    node_context = node.capability.get_extended_runbook(AzureNodeSchema, AZURE)
    location = node_context.location
    storage_account_name = get_storage_account_name(
        subscription_id=subscription_id, location=location
    )
    is_public_container = container_name.endswith("-public")
    blob_data = script or f"touch {test_file}"

    container_client = get_or_create_storage_container(
        credential=platform.credential,
        cloud=platform.cloud,
        account_name=storage_account_name,
        container_name=container_name,
        platform=platform,
    )

    blob = container_client.get_blob_client(blob_name)
    if not blob.exists():
        if is_public_container:
            try:
                container_client.set_container_access_policy(
                    signed_identifiers={}, public_access="container"
                )
            except ResourceExistsError as ex:
                if (
                    "public access is not permitted on this storage account"
                    in str(ex).lower()
                ):
                    raise SkippedException(
                        "Public access is not permitted on this storage account "
                        f"{storage_account_name}. {ex}"
                    )
                raise ex
        # Upload blob to container if doesn't exist
        container_client.upload_blob(
            name=blob_name, data=blob_data, blob_type=blob_type
        )

    blob_url = blob.url

    if is_sas:
        sas_token = generate_user_delegation_sas_token(
            container_name=blob.container_name,
            blob_name=blob.blob_name,
            credential=platform.credential,
            cloud=platform.cloud,
            account_name=storage_account_name,
            platform=platform,
        )

        blob_url = blob_url + "?" + sas_token

    return blob_url


def retrieve_storage_account_name_and_key(
    node: Node,
    environment: Environment,
) -> Any:
    platform = environment.platform
    assert isinstance(platform, AzurePlatform)

    subscription_id = platform.subscription_id
    node_context = node.capability.get_extended_runbook(AzureNodeSchema, AZURE)
    location = node_context.location
    storage_account_name = get_storage_account_name(
        subscription_id=subscription_id, location=location
    )

    return get_storage_credential(
        credential=platform.credential,
        subscription_id=subscription_id,
        cloud=platform.cloud,
        account_name=storage_account_name,
        resource_group_name=AZURE_SHARED_RG_NAME,
    )
