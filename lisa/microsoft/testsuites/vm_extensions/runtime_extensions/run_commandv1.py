# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import gzip
import random
from typing import Any, Dict

from azure.core.exceptions import HttpResponseError
from microsoft.testsuites.vm_extensions.runtime_extensions.common import (
    retrieve_storage_account_name_and_key,
    retrieve_storage_blob_url,
)
from microsoft.testsuites.vm_extensions.vm_extension_base import VmExtensionTestBase

from lisa import Logger, Node, TestCaseMetadata, TestSuiteMetadata, simple_requirement
from lisa.environment import Environment
from lisa.operating_system import BSD
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.tools import Waagent


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    This test suite tests the functionality of the Run Command v1 VM extension.

    ** Same set of tests as CSE **

    It has 12 test cases to verify if RCv1 runs successfully when provided:
    1. File uri and command in public settings
    2. Two file uris and command for downloading second script in settings
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
    tags=["VM_Extension", "RunCommandLinux"],
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        unsupported_os=[BSD],
    ),
)
class RunCommandV1Tests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.CPlat.Core"
    EXTENSION_TYPE = "RunCommandLinux"
    EXTENSION_KEY = "run_command_v1"
    DEFAULT_VERSION = "1.0"

    @TestCaseMetadata(
        description="""
        Basic boot validation for the Run Command v1 VM extension.

        Installs the extension with a single inline commandToExecute and no file
        URIs, so it needs no storage account or public blob access. Verifies that
        provisioning succeeds, then removes the extension.

        The extension publisher and type are read from runbook variables
        (extension_publisher, extension_type), defaulting to the Run Command v1
        extension. The extension_version runbook variable is required; the test
        is skipped if it is not set. The deployed extension is named
        '<publisher>_<extension_type>_boot_validation_test'.
        """,
        priority=5,
        maturity="preview",
    )
    def microsoft_cplat_core_runcommandlinux_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._boot_validation(
            node=node,
            log=log,
            variables=variables,
            settings={"commandToExecute": "echo 'RCv1 boot validation success'"},
        )

    @TestCaseMetadata(
        description="""
        Runs the Run Command v2 VM extension with a public Azure storage file uri.

        Downgrading priority from 3 to 5. Due to the requirement for blob public access,
        which is restricted for security reasons.
        """,
        priority=5,
    )
    def verify_public_script_run(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        variables: Dict[str, Any],
    ) -> None:
        container_name = "rcv1lisa-public"
        blob_name = "public.sh"
        test_file = "/tmp/rcv1-public.txt"

        blob_url = retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=blob_name,
            test_file=test_file,
        )

        settings = {"fileUris": [blob_url], "commandToExecute": f"sh {blob_name}"}

        self._create_and_verify_extension_run(
            node=node,
            variables=variables,
            settings=settings,
            test_file=test_file,
            expected_exit_code=0,
        )

    @TestCaseMetadata(
        description="""
        Runs the Run Command v1 VM extension with 2 public file uris passed in
        and second script being run. Verifies second script created.

        Downgrading priority from 3 to 5. Due to the requirement for blob public access,
        which is restricted for security reasons.
        """,
        priority=5,
    )
    def verify_second_public_script_run(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        variables: Dict[str, Any],
    ) -> None:
        container_name = "rcv1lisa-public"
        first_blob_name = "public.sh"
        first_test_file = "/tmp/rcv1-public.txt"
        second_blob_name = "public2.sh"
        second_test_file = "/tmp/rcv1-public2.txt"

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

        self._create_and_verify_extension_run(
            node=node,
            variables=variables,
            settings=settings,
            test_file=second_test_file,
            expected_exit_code=0,
        )

    @TestCaseMetadata(
        description="""
        Runs the Run Command v1 VM extension with public file uri and command
        in both public and protected settings.

        Downgrading priority from 3 to 5. Due to the requirement for blob public access,
        which is restricted for security reasons.
        """,
        priority=5,
    )
    def verify_script_in_both_settings_failed(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        variables: Dict[str, Any],
    ) -> None:
        container_name = "rcv1lisa-public"
        blob_name = "public.sh"
        test_file = "/tmp/rcv1-public.txt"

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
        self._create_and_verify_extension_run(
            node=node,
            variables=variables,
            settings=settings,
            protected_settings=settings,
            assert_exception=HttpResponseError,
        )

    @TestCaseMetadata(
        description="""
        Runs the Run Command v1 VM extension with public file uri and command in
        protected settings.

        Downgrading priority from 3 to 5. Due to the requirement for blob public access,
        which is restricted for security reasons.
        """,
        priority=5,
    )
    def verify_public_script_protected_settings_run(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        variables: Dict[str, Any],
    ) -> None:
        container_name = "rcv1lisa-public"
        blob_name = "protected-settings.sh"
        test_file = "/tmp/rcv1-protected-settings.txt"

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

        self._create_and_verify_extension_run(
            node=node,
            variables=variables,
            protected_settings=protected_settings,
            test_file=test_file,
            expected_exit_code=0,
        )

    @TestCaseMetadata(
        description="""
        Runs the Run Command v1 VM extension without a command and a script.

        Downgrading priority from 3 to 5. Due to the requirement for blob public access,
        which is restricted for security reasons.
        """,
        priority=5,
    )
    def verify_public_script_without_command_run_failed(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        variables: Dict[str, Any],
    ) -> None:
        container_name = "rcv1lisa-public"
        blob_name = "public.sh"
        test_file = "/tmp/rcv1-public.txt"

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
        self._create_and_verify_extension_run(
            node=node,
            variables=variables,
            settings=settings,
            assert_exception=HttpResponseError,
        )

    @TestCaseMetadata(
        description="""
        Runs the Run Command v1 VM extension with a base64 script
        and command with no file uris.
        """,
        priority=3,
    )
    def verify_base64_script_with_command_run_failed(
        self,
        log: Logger,
        node: Node,
        variables: Dict[str, Any],
    ) -> None:
        test_file = "/tmp/rcv1-base64-command.txt"

        script = f"#!/bin/sh\ntouch {test_file}"
        script_base64 = base64.b64encode(bytes(script, "utf-8")).decode("utf-8")

        settings = {"script": script_base64, "commandToExecute": "sh script.sh"}

        self._create_and_verify_extension_run(
            node=node,
            variables=variables,
            settings=settings,
            assert_exception=HttpResponseError,
        )

    @TestCaseMetadata(
        description="""
        Runs the Custom Script VM extension with a base64 script.

        Downgrading priority from 3 to 5. Due to the requirement for blob public access,
        which is restricted for security reasons.
        """,
        priority=5,
    )
    def verify_public_script_with_base64_script_run(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        variables: Dict[str, Any],
    ) -> None:
        container_name = "rcv1lisa-public"
        blob_name = "base64-script.sh"
        test_file = "/tmp/rcv1-base64-script.txt"

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

        self._create_and_verify_extension_run(
            node=node,
            variables=variables,
            settings=settings,
            test_file=test_file,
            expected_exit_code=0,
        )

    @TestCaseMetadata(
        description="""
        Runs the Run Command v1 VM extension with a gzip'ed base64 script.

        Downgrading priority from 3 to 5. Due to the requirement for blob public access,
        which is restricted for security reasons.
        """,
        priority=5,
    )
    def verify_public_script_with_gzip_base64_script_run(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        variables: Dict[str, Any],
    ) -> None:
        container_name = "rcv1lisa-public"
        blob_name = "base64-gzip.sh"
        test_file = "/tmp/rcv1-base64-gzip.txt"

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

        self._create_and_verify_extension_run(
            node=node,
            variables=variables,
            settings=settings,
            test_file=test_file,
            expected_exit_code=0,
        )

    @TestCaseMetadata(
        description="""
        Runs the Run Command v1 VM extension with private Azure storage file uri
        without a sas token.
        """,
        priority=3,
        use_new_environment=True,
    )
    def verify_private_script_without_sas_run_failed(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        variables: Dict[str, Any],
    ) -> None:
        container_name = "rcv1lisa"
        blob_name = "no-sas.sh"
        random_str = "".join(random.sample("0123456789", 10))
        test_file = f"/tmp/rcv1-no-sas-{random_str}.txt"

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
        self._create_and_verify_extension_run(
            node=node,
            variables=variables,
            settings=settings,
            assert_exception=HttpResponseError,
        )

    @TestCaseMetadata(
        description="""
        Runs the Run Command v1 VM extension with private Azure storage file uri
        without a sas token but with storage account credentials.

        Downgrading priority from 3 to 5. The extension relies on the
         storage account key, which we cannot use currently.
        """,
        priority=5,
    )
    def verify_private_script_with_storage_credentials_run(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        variables: Dict[str, Any],
    ) -> None:
        container_name = "rcv1lisa"
        blob_name = "storage-creds.sh"
        test_file = "/tmp/rcv1-storage-creds.txt"

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

        self._create_and_verify_extension_run(
            node=node,
            variables=variables,
            settings=settings,
            protected_settings=protected_settings,
            test_file=test_file,
            expected_exit_code=0,
        )

    @TestCaseMetadata(
        description="""
        Runs the Run Command v1 VM extension with private Azure storage file uri
        with a sas token.
        """,
        priority=3,
    )
    def verify_private_sas_script_run(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        variables: Dict[str, Any],
    ) -> None:
        container_name = "rcv1lisa"
        blob_name = "sas.sh"
        test_file = "/tmp/rcv1-sas.txt"

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

        self._create_and_verify_extension_run(
            node=node,
            variables=variables,
            settings=settings,
            test_file=test_file,
            expected_exit_code=0,
        )

    @TestCaseMetadata(
        description="""
        Runs the Run Command v1 VM extension with a public Azure storage file uri
        pointing to a python script.

        Downgrading priority from 3 to 5. Due to the requirement for blob public access,
        which is restricted for security reasons.
        """,
        priority=5,
    )
    def verify_public_python_script_run(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        variables: Dict[str, Any],
    ) -> None:
        container_name = "rcv1lisa-public"
        blob_name = "python.py"
        test_file = "/tmp/rcv1-python.txt"
        python_command, _ = node.tools[Waagent].get_python_cmd()

        blob_url = retrieve_storage_blob_url(
            node=node,
            environment=environment,
            container_name=container_name,
            blob_name=blob_name,
            test_file=test_file,
            script=f"#!/usr/bin/env python\nopen('{test_file}', 'a').close()",
        )

        settings = {
            "fileUris": [blob_url],
            "commandToExecute": f"{python_command} {blob_name}",
        }

        self._create_and_verify_extension_run(
            node=node,
            variables=variables,
            settings=settings,
            test_file=test_file,
            expected_exit_code=0,
        )
