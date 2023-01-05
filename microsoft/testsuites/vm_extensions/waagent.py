# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import uuid

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import FreeBSD
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.util import SkippedException


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="BVT for VM Agent",
    requirement=simple_requirement(unsupported_os=[]),
)
class WaAgentBvt(TestSuite):
    @TestCaseMetadata(
        description="""
        Runs the custom script extension and verifies it executed on the
        remote machine.
        """,
        priority=1,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_vm_agent(self, log: Logger, node: Node) -> None:
        # Some of the most common extensions, including Custom Script, are
        # not supported on FreeBSD so skip the test on that case.
        if isinstance(node.os, FreeBSD):
            raise SkippedException(f"unsupported distro type: {type(node.os)}")

        # Any extension will do, use CustomScript for convenience.
        # Use the extension to create a unique file on the test machine.
        unique_name = str(uuid.uuid4())
        test_file = f"/tmp/{unique_name}"
        script = f"touch {test_file} && echo Created {test_file}"
        settings = {"commandToExecute": script}
        extension = node.features[AzureExtension]
        result = extension.create_or_update(
            name="CustomScript",
            publisher="Microsoft.Azure.Extensions",
            type_="CustomScript",
            type_handler_version="2.0",
            auto_upgrade_minor_version=True,
            settings=settings,
            force_update_tag=test_file,
        )
        assert_that(result["provisioning_state"]).described_as(
            "Expected the extension to succeed"
        ).is_equal_to("Succeeded")

        # Double-check that the file was actually created.
        message = f"File {test_file} was not created on the test machine"
        node.execute(
            f"ls '{test_file}'",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=message,
        )
