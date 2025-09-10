# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict

from assertpy import assert_that

from lisa import (
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
)
from lisa.features import NestedVirtualization
from lisa.node import Node
from lisa.testsuite import simple_requirement
from lisa.tools import Cat, Echo, Qemu, Sshpass, Wget
from lisa.util import BadEnvironmentStateException
from lisa.util.logger import Logger
from microsoft.testsuites.nested.common import (
    NESTED_VM_TEST_FILE_CONTENT,
    NESTED_VM_TEST_FILE_NAME,
    NESTED_VM_TEST_PUBLIC_FILE_URL,
    parse_nested_image_variables,
    qemu_connect_nested_vm,
)


@TestSuiteMetadata(
    area="nested",
    category="functional",
    description="""
    This test suite is used to run nested vm related tests.
    """,
)
class Nested(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case will run basic tests on provisioned L2 vm.
        Steps:
        1. Create L2 VM with Qemu.
        2. Verify that files can be copied from L1 VM to L2 VM.
        3. Verify that files from internet can be downloaded to L2 VM.
        """,
        priority=1,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                data_disk_count=search_space.IntRange(min=1),
                data_disk_size=search_space.IntRange(min=12),
            ),
            supported_features=[NestedVirtualization],
        ),
    )
    def verify_nested_kvm_basic(
        self, node: RemoteNode, variables: Dict[str, Any]
    ) -> None:
        (
            nested_image_username,
            nested_image_password,
            nested_image_port,
            nested_image_url,
        ) = parse_nested_image_variables(variables)

        # get l2 vm
        l2_vm = qemu_connect_nested_vm(
            node,
            nested_image_username,
            nested_image_password,
            nested_image_port,
            nested_image_url,
        )

        # verify file is correctly copied from L1 VM to L2 VM
        node.tools[Echo].write_to_file(
            NESTED_VM_TEST_FILE_CONTENT,
            node.get_pure_path(NESTED_VM_TEST_FILE_NAME),
        )
        node.tools[Sshpass].copy(
            NESTED_VM_TEST_FILE_NAME,
            NESTED_VM_TEST_FILE_NAME,
            "localhost",
            nested_image_username,
            nested_image_password,
            nested_image_port,
        )

        uploaded_message = l2_vm.tools[Cat].read(NESTED_VM_TEST_FILE_NAME)
        assert_that(
            uploaded_message,
            "Content of the file uploaded to L2 vm from L1 should match",
        ).is_equal_to(NESTED_VM_TEST_FILE_CONTENT)

        # verify that files could be downloaded from internet on L2 VM
        l2_vm.tools[Wget].get(NESTED_VM_TEST_PUBLIC_FILE_URL)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        # cleanup any nested VM's added as part of the test
        # If the cleanup operation fails, mark node to be recycled
        try:
            node: Node = kwargs.pop("node")
            node.tools[Qemu].delete_vm()
        except Exception:
            raise BadEnvironmentStateException
