# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict, List

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


class CommandInfo(object):
    def __init__(
        self, command: str, expected_exit_code: int, failure_message: str
    ) -> None:
        self.command = command
        self.expected_exit_code = expected_exit_code
        self.failure_message = failure_message


def _create_and_verify_extension_run(
    node: Node,
    settings: Dict[str, Any],
    protected_settings: Dict[str, Any],
    execute_commands: List[CommandInfo],
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

    for command_info in execute_commands:
        node.execute(
            command_info.command,
            shell=True,
            expected_exit_code=command_info.expected_exit_code,
            expected_exit_code_failure_message=command_info.failure_message,
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
    area="vm_extensions1",
    category="functional",
    description="""
    This test suite tests the functionality of the Custom Script VM extension.

    It has 1 test cases to verify if CSE runs successfully when:
        1. 
    """,
)
class CustomScriptTests(TestSuite):
    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with a public script in Azure storage.
        """,
        priority=3,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_public_shell_script_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa-public"
        blob_name = "cselisa.sh"
        test_file = "/tmp/lisatest.txt"

        blob_url = _retrieve_storage_blob_url(
            node, environment, container_name, blob_name, test_file, True
        )

        settings = {"fileUris": [blob_url], "commandToExecute": f"sh {blob_name}"}
        message = f"File {test_file} was not created on the test machine"

        _create_and_verify_extension_run(
            node, settings, {}, [CommandInfo(f"ls '{test_file}'", 0, message)]
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with 2 fileUris passed in
        and only the second script being run.
        """,
        priority=3,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_second_public_shell_script_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa-public"
        first_blob_name = "cselisa.sh"
        first_test_file = "/tmp/lisatest.txt"
        second_blob_name = "cselisa2.sh"
        second_test_file = "/tmp/lisatest2.txt"

        first_blob_url = _retrieve_storage_blob_url(
            node, environment, container_name, first_blob_name, first_test_file, True
        )
        second_blob_url = _retrieve_storage_blob_url(
            node, environment, container_name, second_blob_name, second_test_file, True
        )

        settings = {
            "fileUris": [first_blob_url, second_blob_url],
            "commandToExecute": f"sh {second_blob_name}",
        }
        first_message = f"File {first_test_file} downloaded on test machine though it should not have"
        second_message = f"File {second_test_file} was not created on the test machine"

        _create_and_verify_extension_run(
            node,
            settings,
            {},
            [
                CommandInfo(f"ls '{first_test_file}'", 2, first_message),
                CommandInfo(f"ls '{second_test_file}'", 0, second_message),
            ],
        )
