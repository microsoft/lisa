# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict

from assertpy import assert_that

from lisa import RemoteNode, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import Debian, Fedora, Suse
from lisa.schema import Node
from lisa.tools import Cat, Echo, Lscpu, Qemu, Sshpass, Wget
from lisa.tools.df import Df, PartitionInfo
from lisa.util import SkippedException


@TestSuiteMetadata(
    area="nested",
    category="functional",
    description="""
    This test suite is used to run nested vm related tests.
    """,
)
class Nested(TestSuite):
    NESTED_VM_IMAGE_NAME = "image.qcow2"
    NESTED_VM_TEST_FILE_NAME = "message.txt"
    NESTED_VM_TEST_FILE_CONTENT = "Message from L1 vm!!"
    NESTED_VM_TEST_PUBLIC_FILE_URL = "http://www.github.com"
    NESTED_VM_REQUIRED_DISK_SIZE_IN_GB = 6

    @TestCaseMetadata(
        description="""
        This test case will run basic tests on provisioned L2 vm.
        Steps:
        1. Create L2 VM with Qemu.
        2. Verify that files can be copied from L1 VM to L2 VM.
        3. Verify that files from internet can be downloaded to L2 VM.
        """,
        priority=1,
    )
    def verify_nested_kvm_basic(
        self, node: RemoteNode, variables: Dict[str, Any]
    ) -> None:
        # verify that virtualization is enabled in hardware
        is_virtualization_enabled = node.tools[Lscpu].is_virtualization_enabled()
        if not is_virtualization_enabled:
            raise SkippedException("Virtualization is not enabled in hardware")

        # verify os compatibility
        if not (
            isinstance(node.os, Debian)
            or isinstance(node.os, Fedora)
            or isinstance(node.os, Suse)
        ):
            raise SkippedException(
                f"{node.os} is not supported. Currently the test could be "
                "run on Debian, Fedora and Suse distros."
            )

        # fetch nested vm test variables
        nested_image_username = variables.get("nested_image_username", "")
        nested_image_password = variables.get("nested_image_password", "")
        nested_image_port = 60024
        nested_image_url = variables.get("nested_image_url", "")

        if not nested_image_username:
            raise SkippedException("Nested image username should not be empty")

        if not nested_image_password:
            raise SkippedException("Nested image password should not be empty")

        if not nested_image_url:
            raise SkippedException("Nested image url should not be empty")

        # get l2 vm
        l2_vm = self._connect_nested_vm(
            node,
            nested_image_username,
            nested_image_password,
            nested_image_port,
            nested_image_url,
        )

        # verify file is correctly copied from L1 VM to L2 VM
        node.tools[Echo].write_to_file(
            self.NESTED_VM_TEST_FILE_CONTENT,
            node.get_pure_path(self.NESTED_VM_TEST_FILE_NAME),
        )
        node.tools[Sshpass].copy(
            self.NESTED_VM_TEST_FILE_NAME,
            self.NESTED_VM_TEST_FILE_NAME,
            node.public_address,
            nested_image_username,
            nested_image_password,
            nested_image_port,
        )

        uploaded_message = l2_vm.tools[Cat].read(self.NESTED_VM_TEST_FILE_NAME)
        assert_that(
            uploaded_message,
            "Content of the file uploaded to L2 vm from L1 should match",
        ).is_equal_to(self.NESTED_VM_TEST_FILE_CONTENT)

        # verify that files could be downloaded from internet on L2 VM
        l2_vm.tools[Wget].get(self.NESTED_VM_TEST_PUBLIC_FILE_URL)

    def _check_partition_capacity(
        self,
        partition: PartitionInfo,
    ) -> bool:
        # check if the partition has enough space to download nested image file
        unused_partition_size_in_gb = (
            partition.total_blocks - partition.used_blocks
        ) / (1024 * 1024)
        if unused_partition_size_in_gb > self.NESTED_VM_REQUIRED_DISK_SIZE_IN_GB:
            return True

        return False

    def _get_partition_for_nested_image(self, node: RemoteNode) -> str:
        home_partition = node.tools[Df].get_partition_by_mountpoint("/home")
        if home_partition and self._check_partition_capacity(home_partition):
            return home_partition.mountpoint

        mnt_partition = node.tools[Df].get_partition_by_mountpoint("/mnt")
        if mnt_partition and self._check_partition_capacity(mnt_partition):
            return mnt_partition.mountpoint

        raise SkippedException(
            "No partition with Required disk space of "
            f"{self.NESTED_VM_REQUIRED_DISK_SIZE_IN_GB}GB found"
        )

    def _connect_nested_vm(
        self,
        host: RemoteNode,
        guest_username: str,
        guest_password: str,
        guest_port: int,
        guest_image_url: str,
    ) -> RemoteNode:
        image_folder_path = self._get_partition_for_nested_image(host)
        host.tools[Wget].get(
            url=guest_image_url,
            file_path=image_folder_path,
            filename=self.NESTED_VM_IMAGE_NAME,
            sudo=True,
        )

        # start nested vm
        host.tools[Qemu].create_vm(
            guest_port, f"{image_folder_path}/{self.NESTED_VM_IMAGE_NAME}"
        )

        # setup connection to nested vm
        nested_vm = RemoteNode(Node(name="L2-vm"), 0, "L2-vm")
        nested_vm.set_connection_info(
            public_address=host.public_address,
            username=guest_username,
            password=guest_password,
            public_port=guest_port,
            port=guest_port,
        )

        return nested_vm
