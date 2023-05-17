# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import uuid

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)

from assertpy import assert_that

# from assertpy import assert_that
from lisa.sut_orchestrator.azure.features import AzureExtension


@TestSuiteMetadata(
    area="vm_extensions",
    category="functional",
    description="""
    This test suite tests the functionality of the Run Command v2 VM extension.

    It has 3 test cases to verify if RC runs successfully when:
        1. Used with a pre-existing available script hardcoded in CRP
        2. Provided a custom linux shell script
        3. Provided a storage blob that contains the script
    """,
)
class RunCommand(TestSuite):
    @TestCaseMetadata(
        description="""
        Runs the Run Command v2 VM extension with a pre-existing ifconfig script.
        """,
        priority=1,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_existing_script_run(self, log: Logger, node: Node) -> None:
        settings = {"source": {"CommandId": "ifconfig"}}

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

    @TestCaseMetadata(
        description="""
        Runs the Run Command v2 VM extension with a custom shell script.
        """,
        priority=1,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_custom_script_run(self, log: Logger, node: Node) -> None:
        test_file = f"/tmp/{str(uuid.uuid4())}"
        settings = {
            "source": {"CommandId": "RunShellScript", "script": f"touch {test_file}"}
        }

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

        message = f"File {test_file} was not created on the test machine"
        # Verify that file was created on the test machine
        node.execute(
            f"ls '{test_file}'",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=message,
        )
