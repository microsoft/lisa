# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)

from lisa.environment import Environment
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    AZURE_SHARED_RG_NAME,
    AzureNodeSchema,
    generate_blob_sas_token,
    get_or_create_storage_container,
    get_storage_account_name,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform


def _create_and_verify_extension_run(
    node: Node,
    settings: Dict[str, Any],
    execute_command: str = "",
    exit_code: int = 0,
    message: str = "",
) -> None:
    extension = node.features[AzureExtension]
    result = extension.create_or_update(
        name="CustomScript",
        publisher="Microsoft.Azure.Extensions",
        type_="CustomScript",
        type_handler_version="2.1",
        auto_upgrade_minor_version=True,
        settings=settings,
    )

    assert_that(result["provisioning_state"]).described_as(
        "Expected the extension to succeed"
    ).is_equal_to("Succeeded")

    if len(execute_command) > 0:
        node.execute(
            execute_command,
            shell=True,
            expected_exit_code=exit_code,
            expected_exit_code_failure_message=message,
        )


def _retrieve_storage_blob_url(
    node: Node,
    environment: Environment,
    container_name: str,
    blob_name: str,
    test_file: str,
    is_public_container: bool = False,
    is_sas: bool = False,
) -> Any:
    platform = environment.platform
    assert isinstance(platform, AzurePlatform)

    subscription_id = platform.subscription_id
    node_context = node.capability.get_extended_runbook(AzureNodeSchema, AZURE)
    location = node_context.location
    storage_account_name = get_storage_account_name(
        subscription_id=subscription_id, location=location
    )

    container_client = get_or_create_storage_container(
        credential=platform.credential,
        subscription_id=subscription_id,
        cloud=platform.cloud,
        account_name=storage_account_name,
        container_name=container_name,
        resource_group_name=AZURE_SHARED_RG_NAME,
    )

    blob = container_client.get_blob_client(blob_name)
    if not blob.exists():
        if is_public_container:
            container_client.set_container_access_policy(
                signed_identifiers={}, public_access="container"
            )
        # Upload blob to container if doesn't exist
        container_client.upload_blob(
            name=blob_name, data=f"touch {test_file}"  # type: ignore
        )

    blob_url = blob.url

    if is_sas:
        sas_token = generate_blob_sas_token(
            credential=platform.credential,
            subscription_id=subscription_id,
            cloud=platform.cloud,
            account_name=storage_account_name,
            resource_group_name=AZURE_SHARED_RG_NAME,
            container_name=container_name,
            file_name=blob_name,
            expired_hours=1,
        )

        blob_url = blob_url + "?" + sas_token

    return blob_url


@TestSuiteMetadata(
    area="vm_extensions",
    category="functional",
    description="""
    This test suite tests the functionality of the Custom Script VM extension.

    It has 1 test cases to verify if CSE runs successfully when:
        1. 
    """,
)
class CustomScriptExtension(TestSuite):
    pass
