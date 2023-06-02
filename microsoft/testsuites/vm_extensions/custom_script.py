# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64

import gzip

import logging

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
from lisa.operating_system import BSD
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator import AZURE
from microsoft.testsuites.vm_extensions.common import (
    CommandInfo,
    retrieve_storage_blob_url,
    retrieve_storage_account_name_and_key,
    verify_waagent_version_supported,
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


@TestSuiteMetadata(
    area="vm_extensions",
    category="functional",
    description="""
    This test suite tests the functionality of the Custom Script VM extension.

    File uri is a public Azure storage blob uri unless mentioned otherwise.
    File uri points to a linux shell script unless mentioned otherwise.

    It has 12 test cases to verify if CSE runs as intended when provided:
        1. File uri and command in public settings
        2. Two file uris and command for downloading both scripts in public settings
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
    requirement=simple_requirement(unsupported_os=[BSD]),
)
class CustomScriptTests(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        verify_waagent_version_supported(environment=environment)

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with a public Azure storage file uri.
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[AzureExtension], supported_platform_type=[AZURE]
        ),
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
            node=node,
            settings=settings,
            execute_commands=[CommandInfo(test_file, 0)],
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with 2 public file uris passed in
        and both scripts being run.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[AzureExtension], supported_platform_type=[AZURE]
        ),
    )
    def verify_both_public_scripts_run(
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
        requirement=simple_requirement(
            supported_features=[AzureExtension], supported_platform_type=[AZURE]
        ),
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
        requirement=simple_requirement(
            supported_features=[AzureExtension], supported_platform_type=[AZURE]
        ),
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
            execute_commands=[CommandInfo(test_file, 0)],
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension without a command and a script.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[AzureExtension], supported_platform_type=[AZURE]
        ),
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
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_base64_script_with_command_run(self, log: Logger, node: Node) -> None:
        test_file = "/tmp/lisatest.txt"

        script = f"#!/bin/sh\touch {test_file}"
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
        requirement=simple_requirement(
            supported_features=[AzureExtension], supported_platform_type=[AZURE]
        ),
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
            node=node,
            settings=settings,
            execute_commands=[CommandInfo(test_file, 0)],
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with a gzip'ed base64 script.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[AzureExtension], supported_platform_type=[AZURE]
        ),
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
        requirement=simple_requirement(
            supported_features=[AzureExtension], supported_platform_type=[AZURE]
        ),
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
        requirement=simple_requirement(
            supported_features=[AzureExtension], supported_platform_type=[AZURE]
        ),
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

        credentials = retrieve_storage_account_name_and_key(
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
            execute_commands=[CommandInfo(test_file, 0)],
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with private Azure storage file uri
        with a sas token.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[AzureExtension], supported_platform_type=[AZURE]
        ),
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
            node=node,
            settings=settings,
            execute_commands=[CommandInfo(test_file, 0)],
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with a public Azure storage file uri
        pointing to a python script.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[AzureExtension], supported_platform_type=[AZURE]
        ),
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
            node=node,
            settings=settings,
            execute_commands=[CommandInfo(test_file, 0)],
        )
