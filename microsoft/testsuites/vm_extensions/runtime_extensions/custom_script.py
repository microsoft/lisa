# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import gzip
from typing import Any, Dict, Optional

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
from lisa.operating_system import BSD
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    AZURE_SHARED_RG_NAME,
    AzureNodeSchema,
    get_storage_account_name,
    get_storage_credential,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from microsoft.testsuites.vm_extensions.runtime_extensions.common import (
    check_waagent_version_supported,
    execute_command,
    retrieve_storage_blob_url,
)


def _retrieve_storage_account_name_and_key(
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


def _create_and_verify_extension_run(
    node: Node,
    settings: Optional[Dict[str, Any]] = None,
    protected_settings: Optional[Dict[str, Any]] = None,
    test_file: Optional[str] = None,
    expected_exit_code: Optional[int] = None,
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
            settings=settings or {},
            protected_settings=protected_settings or {},
        )
        return result

    if assert_exception:
        assert_that(enable_extension).raises(assert_exception).when_called_with()
    else:
        result = enable_extension()
        assert_that(result["provisioning_state"]).described_as(
            "Expected the extension to succeed"
        ).is_equal_to("Succeeded")

    if test_file is not None and expected_exit_code is not None:
        execute_command(
            file_name=test_file, expected_exit_code=expected_exit_code, node=node
        )


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    This test suite tests the functionality of the Custom Script VM extension.

    File uri is a public Azure storage blob uri unless mentioned otherwise.
    File uri points to a linux shell script unless mentioned otherwise.

    It has 12 test cases to verify if CSE runs as intended when provided:
        1. File uri and command in public settings
        2. Two file uris and command for downloading second script in public settings
        3. File uri and command in both public and protected settings (should fail)
        4. File uri without a command or base64 script (should fail)
        5. Both base64 script and command in public settings (should fail)
        6. File uri and base64 script in public settings
        7. File uri and gzip'ed base64 script in public settings
        8. File uri and command in protected settings
        9. Private file uri without sas token or credentials (should fail)
        10. Private file uri with storage account credentials
        11. Private sas file uri and command in public settings
        12. File uri (pointing to python script) and command in public settings
    """,
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        unsupported_os=[BSD],
    ),
)
class CustomScriptTests(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs.pop("node")
        check_waagent_version_supported(node=node)

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with a public Azure storage file uri.
        """,
        priority=1,
    )
    def verify_public_script_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa-public"
        blob_name = "cselisa.sh"
        test_file = "/tmp/lisatest.txt"

        blob_url = retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=blob_name,
            test_file=test_file,
        )

        settings = {"fileUris": [blob_url], "commandToExecute": f"sh {blob_name}"}

        _create_and_verify_extension_run(
            node=node, settings=settings, test_file=test_file, expected_exit_code=0
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with 2 public file uris passed in
        and second script being run. Verifies second script created.
        """,
        priority=3,
    )
    def verify_second_public_script_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa-public"
        first_blob_name = "cselisa.sh"
        first_test_file = "/tmp/lisatest.txt"
        second_blob_name = "cselisa2.sh"
        second_test_file = "/tmp/lisatest2.txt"

        first_blob_url = retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=first_blob_name,
            test_file=first_test_file,
        )
        second_blob_url = retrieve_storage_blob_url(
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
            test_file=second_test_file,
            expected_exit_code=0,
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with public file uri and command
        in both public and protected settings.
        """,
        priority=3,
    )
    def verify_script_in_both_settings_failed(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa"
        blob_name = "cselisa.sh"
        test_file = "/tmp/lisatest.txt"

        blob_url = retrieve_storage_blob_url(
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
    )
    def verify_public_script_protected_settings_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa-public"
        blob_name = "cselisa.sh"
        test_file = "/tmp/lisatest.txt"

        blob_url = retrieve_storage_blob_url(
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
            test_file=test_file,
            expected_exit_code=0,
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension without a command and a script.
        """,
        priority=3,
    )
    def verify_public_script_without_command_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa-public"
        blob_name = "cselisa.sh"
        test_file = "/tmp/lisatest.txt"

        blob_url = retrieve_storage_blob_url(
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
        Runs the Custom Script VM extension with a base64 script
        and command with no file uris.
        """,
        priority=3,
    )
    def verify_base64_script_with_command_run(self, log: Logger, node: Node) -> None:
        test_file = "/tmp/lisatest.txt"

        script = f"#!/bin/sh\ntouch {test_file}"
        script_base64 = base64.b64encode(bytes(script, "utf-8")).decode("utf-8")

        settings = {"script": script_base64, "commandToExecute": "sh script.sh"}

        _create_and_verify_extension_run(
            node=node, settings=settings, assert_exception=HttpResponseError
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with a base64 script.
        """,
        priority=3,
    )
    def verify_public_script_with_base64_script_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa-public"
        blob_name = "cselisa.sh"
        test_file = "/tmp/lisatest.txt"

        script = f"#!/bin/sh\nsh {blob_name}"
        script_base64 = base64.b64encode(bytes(script, "utf-8")).decode("utf-8")

        blob_url = retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=blob_name,
            test_file=test_file,
        )

        settings = {"fileUris": [blob_url], "script": script_base64}

        _create_and_verify_extension_run(
            node=node, settings=settings, test_file=test_file, expected_exit_code=0
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with a gzip'ed base64 script.
        """,
        priority=3,
    )
    def verify_public_script_with_gzip_base64_script_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa-public"
        blob_name = "cselisa.sh"
        test_file = "/tmp/lisatest.txt"

        script = f"#!/bin/sh\nsh {blob_name}"
        compressed_script = gzip.compress(bytes(script, "utf-8"))
        script_base64 = base64.b64encode(compressed_script).decode("utf-8")

        blob_url = retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=blob_name,
            test_file=test_file,
        )

        settings = {"fileUris": [blob_url], "script": script_base64}

        _create_and_verify_extension_run(
            node=node, settings=settings, test_file=test_file, expected_exit_code=0
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with private Azure storage file uri
        without a sas token.
        """,
        priority=3,
    )
    def verify_private_script_without_sas_run_failed(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa"
        blob_name = "cselisa.sh"
        test_file = "/tmp/lisatest.txt"

        blob_url = retrieve_storage_blob_url(
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
        without a sas token but with storage account credentials.
        """,
        priority=3,
    )
    def verify_private_script_with_storage_credentials_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa"
        blob_name = "cselisa.sh"
        test_file = "/tmp/lisatest.txt"

        blob_url = retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=blob_name,
            test_file=test_file,
        )

        credentials = _retrieve_storage_account_name_and_key(
            node=node, environment=environment
        )

        settings = {"fileUris": [blob_url], "commandToExecute": f"sh {blob_name}"}

        protected_settings = {
            "storageAccountName": credentials["account_name"],
            "storageAccountKey": credentials["account_key"],
        }

        _create_and_verify_extension_run(
            node=node,
            settings=settings,
            protected_settings=protected_settings,
            test_file=test_file,
            expected_exit_code=0,
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with private Azure storage file uri
        with a sas token.
        """,
        priority=3,
    )
    def verify_private_sas_script_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa"
        blob_name = "cselisa.sh"
        test_file = "/tmp/lisatest.txt"

        blob_url = retrieve_storage_blob_url(
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
            node=node, settings=settings, test_file=test_file, expected_exit_code=0
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with a public Azure storage file uri
        pointing to a python script.
        """,
        priority=3,
    )
    def verify_public_python_script_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "cselisa-public"
        blob_name = "cselisa.py"
        test_file = "/tmp/lisatest-python.txt"

        blob_url = retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=blob_name,
            test_file=test_file,
            script=f"#!/usr/bin/env python\nopen('{test_file}', 'a').close()",
        )

        settings = {"fileUris": [blob_url], "commandToExecute": f"python3 {blob_name}"}

        _create_and_verify_extension_run(
            node=node, settings=settings, test_file=test_file, expected_exit_code=0
        )
