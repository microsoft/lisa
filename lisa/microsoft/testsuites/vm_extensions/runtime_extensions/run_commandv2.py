# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import uuid
from typing import Any, Dict, Optional

from assertpy import assert_that
from microsoft.testsuites.vm_extensions.runtime_extensions.common import (
    check_waagent_version_supported,
    create_and_verify_vmaccess_extension_run,
    execute_command,
    retrieve_storage_blob_url,
)

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.environment import Environment
from lisa.operating_system import BSD, CBLMariner, CpuArchitecture
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import AzureNodeSchema
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.util import SkippedException


def _check_architecture_supported(node: Node) -> None:
    arch = node.os.get_kernel_information().hardware_platform  # type: ignore
    if arch == CpuArchitecture.ARM64:
        # Support RCv2 on ARM64 Mariner in Canary regions
        if isinstance(node.os, CBLMariner):
            node_context = node.capability.get_extended_runbook(AzureNodeSchema, AZURE)
            canary_locations = ["centraluseuap", "eastus2euap"]
            if node_context.location in canary_locations:
                return

        raise SkippedException("RunCommandv2 Extension not published on ARM64.")


def _create_and_verify_extension_run(
    node: Node,
    settings: Dict[str, Any],
    protected_settings: Optional[Dict[str, Any]] = None,
    test_file: Optional[str] = None,
    expected_exit_code: Optional[int] = None,
) -> None:
    extension = node.features[AzureExtension]
    result = extension.create_or_update(
        name="RunCommandv2",
        publisher="Microsoft.CPlat.Core",
        type_="RunCommandHandlerLinux",
        type_handler_version="1.3",
        auto_upgrade_minor_version=True,
        settings=settings,
        protected_settings=protected_settings or {},
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

    It has 12 test cases to verify if RCv2 runs successfully when provided:
        1. Pre-existing available script hardcoded in CRP
        2. Custom shell script
        3. Script with a named parameter
        4. Script with an unnamed parameter
        5. Script with a named protected parameter
        6. Public storage blob uri that points to the script
        7. Storage uri pointing to script without a sas token (should fail)
        8. Storage sas uri that points to script
        9. Command with a timeout of 1 second (should pass)
        10. Command that should take longer than 1 second, but with a
           timeout of 1 second (should fail)
        11. Provided a different valid user to run a command with
        12. Provided a different invalid user to run a command with (should fail)
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

        _create_and_verify_extension_run(node=node, settings=settings)

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
        Runs the Run Command v2 VM extension with a named public parameter
        passed to a custom shell script.
        """,
        priority=3,
    )
    def verify_script_run_with_named_parameter(self, log: Logger, node: Node) -> None:
        env_var_name = "TestVar"
        test_file = "/tmp/rcv2-named.txt"
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
        Runs the Run Command v2 VM extension with an unnamed public parameter
        passed to a custom shell script.
        """,
        priority=3,
    )
    def verify_script_run_with_unnamed_parameter(self, log: Logger, node: Node) -> None:
        test_file = f"/tmp/{uuid.uuid4()}.txt"
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
        Runs the Run Command v2 VM extension with a named protected parameter
        passed to a custom shell script.
        """,
        priority=3,
    )
    def verify_script_run_with_protected_parameter(
        self, log: Logger, node: Node
    ) -> None:
        env_var_name = "ProtectedVar"
        test_file = f"/tmp/{uuid.uuid4()}.txt"
        settings = {
            "source": {
                "CommandId": "RunShellScript",
                "script": f"touch ${env_var_name}",
            },
        }

        protected_settings = {
            "protectedParameters": [{"Name": env_var_name, "Value": test_file}],
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
        Runs the Run Command v2 VM extension with a public uri pointing to the
        script in blob storage.

        Downgrading priority from 3 to 5. Due to the requirement for blob public access,
        which is restricted for security reasons.
        """,
        priority=5,
    )
    def verify_public_uri_script_run(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        container_name = "rcv2lisa-public"
        blob_name = "public.sh"
        test_file = "/tmp/rcv2-public.txt"
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
        blob_name = "no-sas.sh"
        test_file = "/tmp/rcv2-no-sas.txt"
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
        blob_name = "sas.sh"
        test_file = "/tmp/rcv2-sas.txt"
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
        test_file = f"/tmp/{uuid.uuid4()}.txt"
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
        test_file = f"/tmp/{uuid.uuid4()}.txt"
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

    @TestCaseMetadata(
        description="""
        Runs the Run Command v2 VM extension with a different valid user on the VM.
        """,
        priority=3,
    )
    def verify_script_run_with_valid_user(self, log: Logger, node: Node) -> None:
        username = "vmaccessuser-valid"
        password = str(uuid.uuid4())
        protected_settings = {"username": username, "password": password}

        # Creates a user with given username and password on test VM
        create_and_verify_vmaccess_extension_run(
            node=node, protected_settings=protected_settings
        )

        test_file = "/tmp/rcv2-runas-valid.txt"
        settings = {
            "source": {
                "CommandId": "RunShellScript",
                "script": f"touch {test_file}",
            },
            "runAsUser": username,
        }

        protected_settings = {"runAsPassword": password}

        _create_and_verify_extension_run(
            node=node,
            settings=settings,
            protected_settings=protected_settings,
            test_file=test_file,
            expected_exit_code=0,
        )

    @TestCaseMetadata(
        description="""
        Runs the Run Command v2 VM extension with a different invalid user on the VM.
        """,
        priority=3,
    )
    def verify_script_run_with_invalid_user(self, log: Logger, node: Node) -> None:
        username = "vmaccessuser-valid"
        invalid_username = "vmaccessuser-invalid"
        password = str(uuid.uuid4())
        protected_settings = {"username": username, "password": password}

        # Creates a user with given username and password on test VM
        create_and_verify_vmaccess_extension_run(
            node=node, protected_settings=protected_settings
        )

        test_file = "/tmp/rcv2-runas-invalid.txt"
        settings = {
            "source": {
                "CommandId": "RunShellScript",
                "script": f"touch {test_file}",
            },
            "runAsUser": invalid_username,
        }

        protected_settings = {"runAsPassword": password}

        _create_and_verify_extension_run(
            node=node,
            settings=settings,
            protected_settings=protected_settings,
            test_file=test_file,
            expected_exit_code=2,
        )
