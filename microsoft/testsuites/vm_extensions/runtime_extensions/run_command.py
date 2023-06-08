# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import uuid
from typing import Any, Dict, Optional

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
from lisa.operating_system import BSD, CpuArchitecture
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.util import SkippedException
from microsoft.testsuites.vm_extensions.runtime_extensions.common import (
    check_waagent_version_supported,
    execute_command,
    retrieve_storage_blob_url,
)


def _check_architecture_supported(node: Node) -> None:
    arch = node.os.get_kernel_information().hardware_platform  # type: ignore
    if arch == CpuArchitecture.ARM64:
        raise SkippedException("RunCommandv2 Extension not published on ARM64.")


def _create_and_verify_extension_run(
    node: Node,
    settings: Dict[str, Any],
    test_file: Optional[str] = None,
    expected_exit_code: Optional[int] = None,
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

    if test_file is not None and expected_exit_code is not None:
        execute_command(
            file_name=test_file, expected_exit_code=expected_exit_code, node=node
        )


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    This test suite tests the functionality of the Run Command v2 VM extension.

    It has 9 test cases to verify if RC runs successfully when:
        1. Used with a pre-existing available script hardcoded in CRP
        2. Provided a custom linux shell script
        3. Provided a custom linux shell script with a named parameter
        4. Provided a custom linux shell script with an unnamed parameter
        5. Provided a public storage blob uri that points to the script
        6. Provided a storage uri pointing to script without a sas token (should fail)
        7. Provided a storage sas uri that points to script
        8. Provided a command with a timeout of 1 second (should pass)
        9. Provided a command that should take longer than 1 second, but with a
           timeout of 1 second (should fail)
    """,
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        unsupported_os=[BSD],
    ),
)
class RunCommandV2Tests(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs.pop("node")
        _check_architecture_supported(node=node)
        check_waagent_version_supported(node=node)

    @TestCaseMetadata(
        description="""
        Runs the Run Command v2 VM extension with a pre-existing ifconfig script.
        """,
        priority=1,
    )
    def verify_existing_script_run(self, log: Logger, node: Node) -> None:
        settings = {"source": {"CommandId": "ifconfig"}}

        _create_and_verify_extension_run(node, settings)

    @TestCaseMetadata(
        description="""
        Runs the Run Command v2 VM extension with a custom shell script.
        """,
        priority=3,
    )
    def verify_custom_script_run(self, log: Logger, node: Node) -> None:
        test_file = f"/tmp/{str(uuid.uuid4())}"
        settings = {
            "source": {"CommandId": "RunShellScript", "script": f"touch {test_file}"}
        }

        _create_and_verify_extension_run(
            node=node, settings=settings, test_file=test_file, expected_exit_code=0
        )

    @TestCaseMetadata(
        description="""
        Runs the Run Command v2 VM extension with a named parameter
        passed to a custom shell script.
        """,
        priority=3,
    )
    def verify_script_run_with_named_parameter(self, log: Logger, node: Node) -> None:
        env_var_name = "TestVar"
        test_file = "/tmp/rcv2namedtest.txt"
        settings = {
            "source": {
                "CommandId": "RunShellScript",
                "script": f"touch ${env_var_name}",
            },
            "parameters": [{"Name": env_var_name, "Value": test_file}],
        }

        _create_and_verify_extension_run(
            node=node, settings=settings, test_file=test_file, expected_exit_code=0
        )

    @TestCaseMetadata(
        description="""
        Runs the Run Command v2 VM extension with an unnamed parameter
        passed to a custom shell script.
        """,
        priority=3,
    )
    def verify_script_run_with_unnamed_parameter(self, log: Logger, node: Node) -> None:
        test_file = "/tmp/rcv2unnamedtest.txt"
        settings = {
            "source": {
                "CommandId": "RunShellScript",
                "script": "touch $1",
            },
            "parameters": [{"Name": "", "Value": test_file}],
        }

        _create_and_verify_extension_run(
            node=node, settings=settings, test_file=test_file, expected_exit_code=0
        )

    @TestCaseMetadata(
        description="""
        Runs the Run Command v2 VM extension with a public uri pointing to the
        script in blob storage.
        """,
        priority=3,
    )
    def verify_public_uri_script_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "rcv2lisa-public"
        blob_name = "rcv2lisa.sh"
        test_file = "/tmp/lisatest.txt"
        blob_url = retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=blob_name,
            test_file=test_file,
        )

        settings = {
            "source": {
                "CommandId": "RunShellScript",
                "scriptUri": blob_url,
            },
        }

        _create_and_verify_extension_run(
            node=node, settings=settings, test_file=test_file, expected_exit_code=0
        )

    @TestCaseMetadata(
        description="""
        Runs the Run Command v2 VM extension with a private storage uri pointing
        to the script in blob storage. No sas token provided, should fail.
        """,
        priority=3,
    )
    def verify_private_uri_script_run_failed(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "rcv2lisa"
        blob_name = "rcv2lisa.sh"
        test_file = "/tmp/rcv2lisasas.txt"
        blob_url = retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=blob_name,
            test_file=test_file,
        )

        settings = {
            "source": {
                "CommandId": "RunShellScript",
                "scriptUri": blob_url,
            },
        }

        _create_and_verify_extension_run(
            node=node, settings=settings, test_file=test_file, expected_exit_code=2
        )

    @TestCaseMetadata(
        description="""
        Runs the Run Command v2 VM extension with a storage sas uri pointing
        to the script in blob storage.
        """,
        priority=3,
    )
    def verify_sas_uri_script_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "rcv2lisa"
        blob_name = "rcv2lisa.sh"
        test_file = "/tmp/rcv2lisasas.txt"
        blob_url = retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=blob_name,
            test_file=test_file,
            is_sas=True,
        )

        settings = {
            "source": {
                "CommandId": "RunShellScript",
                "scriptUri": blob_url,
            },
        }

        _create_and_verify_extension_run(
            node=node, settings=settings, test_file=test_file, expected_exit_code=0
        )

    @TestCaseMetadata(
        description="""
        Runs the Run Command v2 VM extension with a timeout of 0.1 seconds.
        """,
        priority=3,
    )
    def verify_script_run_with_timeout(self, log: Logger, node: Node) -> None:
        test_file = "/tmp/rcv2timeout.txt"
        settings = {
            "source": {
                "CommandId": "RunShellScript",
                "script": f"sleep 0.1; touch {test_file}",
            },
            "timeoutInSeconds": 1,
        }

        _create_and_verify_extension_run(
            node=node, settings=settings, test_file=test_file, expected_exit_code=0
        )

    @TestCaseMetadata(
        description="""
        Runs the Run Command v2 VM extension with a timeout of 1 second.
        """,
        priority=3,
    )
    def verify_script_run_with_timeout_failed(self, log: Logger, node: Node) -> None:
        test_file = "/tmp/rcv2timeout.txt"
        settings = {
            "source": {
                "CommandId": "RunShellScript",
                "script": f"sleep 1.5; touch {test_file}",
            },
            "timeoutInSeconds": 1,
        }

        _create_and_verify_extension_run(
            node=node, settings=settings, test_file=test_file, expected_exit_code=2
        )
