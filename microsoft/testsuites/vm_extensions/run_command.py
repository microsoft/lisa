# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import uuid

from typing import Dict

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.sut_orchestrator.azure.common import (
    AZURE_SHARED_RG_NAME,
    get_storage_account_name,
    get_or_create_storage_container,
    generate_blob_sas_token,
    AzureNodeSchema,
)
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.environment import Environment


def create_and_verify_extension_run(
    node: Node,
    settings: Dict[str, Dict[str, str]],
    execute_command: str | None,
    exit_code: int = 0,
    message: str = "",
) -> None:
    extension = node.features[AzureExtension]
    result = extension.create_or_update(
        name="RunCommand",
        publisher="Microsoft.CPlat.Core",
        type_="RunCommandHandlerLinux",
        type_handler_version="1.3",
        auto_upgrade_minor_version=True,
        settings=settings,
    )

    assert_that(result["provisioning_state"]).described_as(
        "Expected the extension to succeed"
    ).is_equal_to("Succeeded")

    if execute_command:
        node.execute(
            execute_command,
            shell=True,
            expected_exit_code=exit_code,
            expected_exit_code_failure_message=message,
        )


@TestSuiteMetadata(
    area="vm_extensions",
    category="functional",
    description="""
    This test suite tests the functionality of the Run Command v2 VM extension.

    It has 5 test cases to verify if RC runs successfully when:
        1. Used with a pre-existing available script hardcoded in CRP
        2. Provided a custom linux shell script
        3. Provided a public storage blob uri that points to the script
        4. Provided a storage uri pointing to script without a sas token (should fail)
        5. Provided a storage sas uri that points to script
    """,
)
class RunCommand(TestSuite):
    @TestCaseMetadata(
        description="""
        Runs the Run Command v2 VM extension with a pre-existing ifconfig script.
        """,
        priority=3,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_existing_script_run(self, log: Logger, node: Node) -> None:
        settings = {"source": {"CommandId": "ifconfig"}}
        create_and_verify_extension_run(node, settings, None)

    @TestCaseMetadata(
        description="""
        Runs the Run Command v2 VM extension with a custom shell script.
        """,
        priority=3,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_custom_script_run(self, log: Logger, node: Node) -> None:
        test_file = f"/tmp/{str(uuid.uuid4())}"
        settings = {
            "source": {"CommandId": "RunShellScript", "script": f"touch {test_file}"}
        }
        message = f"File {test_file} was not created on the test machine"

        create_and_verify_extension_run(node, settings, f"ls '{test_file}'", 0, message)

    @TestCaseMetadata(
        description="""
        Runs the Run Command v2 VM extension with a public uri pointing to the
        script in blob storage.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[AzureExtension], supported_platform_type=[AZURE]
        ),
    )
    def verify_public_uri_script_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        platform = environment.platform
        assert isinstance(platform, AzurePlatform)

        subscription_id = platform.subscription_id
        container_name = "rcv2lisa-public"
        node_context = node.capability.get_extended_runbook(AzureNodeSchema, AZURE)
        location = node_context.location
        storage_account_name = get_storage_account_name(
            subscription_id=subscription_id, location=location
        )
        blob_name = "rcv2lisa.sh"
        test_file = "/tmp/lisatest.txt"

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
            container_client.set_container_access_policy(
                signed_identifiers={}, public_access="container"
            )
            # Upload blob to container if doesn't exist
            container_client.upload_blob(
                name=blob_name, data=f"touch {test_file}", overwrite=True
            )

        test_file = "/tmp/lisatest.txt"
        settings = {
            "source": {
                "CommandId": "RunShellScript",
                "scriptUri": blob.url,
            },
        }
        message = f"File {test_file} was not created on the test machine"

        create_and_verify_extension_run(node, settings, f"ls '{test_file}'", 0, message)

    @TestCaseMetadata(
        description="""
        Runs the Run Command v2 VM extension with a private storage uri pointing
        to the script in blob storage. No sas token provided, should fail.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[AzureExtension], supported_platform_type=[AZURE]
        ),
    )
    def verify_private_uri_script_run_failed(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        platform = environment.platform
        assert isinstance(platform, AzurePlatform)

        subscription_id = platform.subscription_id
        container_name = "rcv2lisa"
        node_context = node.capability.get_extended_runbook(AzureNodeSchema, AZURE)
        location = node_context.location
        storage_account_name = get_storage_account_name(
            subscription_id=subscription_id, location=location
        )
        blob_name = "rcv2lisa.sh"
        test_file = "/tmp/rcv2lisasas.txt"

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
            # Upload blob to container if doesn't exist
            container_client.upload_blob(
                name=blob_name, data=f"touch {test_file}", overwrite=True
            )

        settings = {
            "source": {
                "CommandId": "RunShellScript",
                "scriptUri": blob.url,
            },
        }
        message = (
            f"File {test_file} downloaded on test machine though it should not have."
        )

        create_and_verify_extension_run(node, settings, f"ls '{test_file}'", 2, message)

    @TestCaseMetadata(
        description="""
        Runs the Run Command v2 VM extension with a storage sas uri pointing
        to the script in blob storage.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[AzureExtension], supported_platform_type=[AZURE]
        ),
    )
    def verify_sas_uri_script_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        platform = environment.platform
        assert isinstance(platform, AzurePlatform)

        subscription_id = platform.subscription_id
        container_name = "rcv2lisa"
        node_context = node.capability.get_extended_runbook(AzureNodeSchema, AZURE)
        location = node_context.location
        storage_account_name = get_storage_account_name(
            subscription_id=subscription_id, location=location
        )
        blob_name = "rcv2lisa.sh"
        test_file = "/tmp/rcv2lisasas.txt"

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
            # Upload blob to container if doesn't exist
            container_client.upload_blob(
                name=blob_name, data=f"touch {test_file}", overwrite=True
            )

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

        script_uri = blob.url + "?" + sas_token
        settings = {
            "source": {
                "CommandId": "RunShellScript",
                "scriptUri": script_uri,
            },
        }
        message = f"File {test_file} was not created on the test machine"

        create_and_verify_extension_run(node, settings, f"ls '{test_file}'", 0, message)
