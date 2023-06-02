# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import uuid
from typing import Any, Dict

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
)
from lisa.environment import Environment
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    AZURE_SHARED_RG_NAME,
    AzureNodeSchema,
    generate_blob_sas_token,
    get_or_create_storage_container,
    get_storage_account_name,
    get_storage_credential,
)
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.util import SkippedException
from semver import VersionInfo


class CommandInfo(object):
    def __init__(
        self,
        file_name: str,
        expected_exit_code: int,
    ) -> None:
        self.command = f"ls '{file_name}'"
        self.expected_exit_code = expected_exit_code
        if expected_exit_code == 0:
            self.failure_message = (
                f"File {file_name} was not created on the test machine"
            )
        else:
            self.failure_message = (
                f"File {file_name} downloaded on test machine though it should not have"
            )


def verify_waagent_version_supported(environment: Environment) -> None:
    platform = environment.platform
    assert isinstance(platform, AzurePlatform)

    env_information = platform.get_environment_information(environment)
    if "wala_version" in env_information:
        wala_version = env_information["wala_version"]
        result = VersionInfo.parse(wala_version).compare("2.4.0")
        if result < 0:
            raise SkippedException(
                f"Node with Windows Azure Linux Agent version {wala_version}"
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
        container_client.upload_blob(name=blob_name, data=blob_data)  # type: ignore

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
