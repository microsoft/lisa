# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64

from typing import Any, Dict, List

from assertpy import assert_that

from azure.core.exceptions import HttpResponseError

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
        self,
        file_name: str,
        expected_exit_code: int,
        # self, command: str, expected_exit_code: int, failure_message: str
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


def _create_and_verify_extension_run(
    node: Node,
    settings: Dict[str, Any] = {},
    protected_settings: Dict[str, Any] = {},
    execute_commands: List[CommandInfo] = [],
    assert_exception: Any = None,
) -> None:
    extension = node.features[AzureExtension]

    def enable_extension() -> Any:
        result = extension.create_or_update(
            name="CustomScript",
            publisher="Microsoft.Azure.Extensions",
            type_="CustomScript",
            type_handler_version="2.1",
            auto_upgrade_minor_version=True,
            settings=settings,
            protected_settings=protected_settings,
        )
        return result

    if assert_exception:
        assert_that(enable_extension).raises(assert_exception).when_called_with()
    else:
        result = enable_extension()
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
    container_name: str = "",
    blob_name: str = "",
    test_file: str = "",
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
    is_public_container = container_name.endswith("-public")

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

    It has 9 test cases to verify if CSE runs as intended when provided:
        1. Public storage blob uri + command in public settings
        2. 2 public blob uris + command for second script in public settings
        3. 2 public blob uris + command for both scripts in public settings
        4. Public blob uri + command in both public and protected settings (should fail)
        5. Public blob uri without a command or base64 script in settings (should fail)
        6. Public blob uri + base64 script in public settings
        7. Public blob uri + command in protected settings
        8. Private blob uri without sas token in public settings (should fail)
        9. Private sas uri + command in public settings
    """,
)
class CustomScriptTests(TestSuite):
    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with a public Azure storage file uri.
        """,
        priority=3,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_public_script_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa-public"
        blob_name = "cselisa.sh"
        test_file = "/tmp/lisatest.txt"

        blob_url = _retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=blob_name,
            test_file=test_file,
        )

        settings = {"fileUris": [blob_url], "commandToExecute": f"sh {blob_name}"}

        _create_and_verify_extension_run(
            node=node,
            settings=settings,
            execute_commands=[CommandInfo(test_file, 0)],
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with 2 public file uris passed in
        and only the second script being run.
        """,
        priority=3,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_second_public_script_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa-public"
        first_blob_name = "cselisa.sh"
        first_test_file = "/tmp/lisatest.txt"
        second_blob_name = "cselisa2.sh"
        second_test_file = "/tmp/lisatest2.txt"

        first_blob_url = _retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=first_blob_name,
            test_file=first_test_file,
        )
        second_blob_url = _retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=second_blob_name,
            test_file=second_test_file,
        )

        settings = {
            "fileUris": [first_blob_url, second_blob_url],
            "commandToExecute": f"sh {second_blob_name}",
        }

        _create_and_verify_extension_run(
            node=node,
            settings=settings,
            execute_commands=[
                CommandInfo(first_test_file, 2),
                CommandInfo(second_test_file, 0),
            ],
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with 2 public file uris passed in
        and both of them being run.
        """,
        priority=3,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_both_public_scripts_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa-public"
        first_blob_name = "cselisa.sh"
        first_test_file = "/tmp/lisatest.txt"
        second_blob_name = "cselisa2.sh"
        second_test_file = "/tmp/lisatest2.txt"

        first_blob_url = _retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=first_blob_name,
            test_file=first_test_file,
        )
        second_blob_url = _retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=second_blob_name,
            test_file=second_test_file,
        )

        settings = {
            "fileUris": [first_blob_url, second_blob_url],
            "commandToExecute": f"sh {first_blob_name}; sh {second_blob_name}",
        }

        _create_and_verify_extension_run(
            node=node,
            settings=settings,
            execute_commands=[
                CommandInfo(first_test_file, 0),
                CommandInfo(second_test_file, 0),
            ],
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with public file uri and command
        in both public and protected settings.
        """,
        priority=3,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_script_in_both_settings_failed(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa"
        blob_name = "cselisa.sh"
        test_file = "/tmp/lisatest.txt"

        blob_url = _retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=blob_name,
            test_file=test_file,
        )

        settings = {
            "fileUris": [blob_url],
            "commandToExecute": f"sh {blob_name}",
        }

        # Expect HttpResponseError
        _create_and_verify_extension_run(
            node=node,
            settings=settings,
            protected_settings=settings,
            assert_exception=HttpResponseError,
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with public file uri and command in
        protected settings.
        """,
        priority=3,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_public_script_protected_settings_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa-public"
        blob_name = "cselisa.sh"
        test_file = "/tmp/lisatest.txt"

        blob_url = _retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=blob_name,
            test_file=test_file,
        )

        protected_settings = {
            "fileUris": [blob_url],
            "commandToExecute": f"sh {blob_name}",
        }

        _create_and_verify_extension_run(
            node=node,
            protected_settings=protected_settings,
            execute_commands=[CommandInfo(test_file, 0)],
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension without a command and a script.
        """,
        priority=3,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_public_script_without_command_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa-public"
        blob_name = "cselisa.sh"
        test_file = "/tmp/lisatest.txt"

        blob_url = _retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=blob_name,
            test_file=test_file,
        )

        settings = {
            "fileUris": [blob_url],
        }

        # Expect HttpResponseError
        _create_and_verify_extension_run(
            node=node,
            settings=settings,
            assert_exception=HttpResponseError,
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with a base64 script.
        """,
        priority=3,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_public_script_with_base64_script_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa-public"
        blob_name = "cselisa.sh"
        test_file = "/tmp/lisatest.txt"

        script = f"#!/bin/sh\nsh {blob_name}"
        script_base64 = base64.b64encode(bytes(script, "utf-8")).decode("utf-8")

        blob_url = _retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=blob_name,
            test_file=test_file,
        )

        settings = {"fileUris": [blob_url], "script": script_base64}

        _create_and_verify_extension_run(
            node=node,
            settings=settings,
            execute_commands=[CommandInfo(test_file, 0)],
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with private Azure storage file uri
        without a sas token.
        """,
        priority=3,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_private_script_without_sas_run_failed(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa"
        blob_name = "cselisa.sh"
        test_file = "/tmp/lisatest.txt"

        blob_url = _retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=blob_name,
            test_file=test_file,
        )

        settings = {
            "fileUris": [blob_url],
            "commandToExecute": f"sh {blob_name}",
        }

        # Expect HttpResponseError
        _create_and_verify_extension_run(
            node=node,
            settings=settings,
            assert_exception=HttpResponseError,
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with private Azure storage file uri
        with a sas token.
        """,
        priority=3,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_private_sas_script_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa"
        blob_name = "cselisa.sh"
        test_file = "/tmp/lisatest.txt"

        blob_url = _retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=blob_name,
            test_file=test_file,
            is_sas=True,
        )

        settings = {
            "fileUris": [blob_url],
            "commandToExecute": f"sh {blob_name}",
        }

        _create_and_verify_extension_run(
            node=node,
            settings=settings,
            execute_commands=[CommandInfo(test_file, 0)],
        )
