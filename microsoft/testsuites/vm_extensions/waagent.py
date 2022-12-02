# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from assertpy import assert_that
from uuid import uuid4

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.sut_orchestrator.azure.features import AzureExtension


@TestSuiteMetadata(
    area="azure",
    category="functional",
    description="BVT for VM Agent",
    requirement=simple_requirement(unsupported_os=[]),
)
class WaAgentBvt(TestSuite):
    @TestCaseMetadata(
        description="""
        Runs an extension and verifies it executed on the remote machine.
        """,
        priority=1,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_vm_agent(self, log: Logger, node: Node) -> None:
        # Any extension will do, use CustomScript for convenience.
        # Use the extension to create a unique file on the test machine.
        test_file = "/tmp/{0}".format(uuid4())
        settings = { "commandToExecute": "touch {0} && echo Created {0}".format(test_file) }
        extension = node.features[AzureExtension]
        result = extension.create_or_update(
            name="CustomScript",
            publisher="Microsoft.Azure.Extensions",
            type="CustomScript",
            type_handler_version="2.0",
            auto_upgrade_minor_version=True,
            settings=settings,
            force_update_tag=test_file
        )
        assert_that(result['provisioning_state']).is_equal_to("Succeeded")

        # Double-check that the file was actually created.
        failure_message = "File {0} was not created on the test machine".format(test_file)
        node.execute(
            "ls '{0}'".format(test_file),
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=failure_message)
