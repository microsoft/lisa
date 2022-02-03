# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict, List, Optional, Tuple

from lisa import RemoteNode
from lisa.operating_system import Debian, Fedora, Suse
from lisa.schema import Node
from lisa.tools import Lscpu, Qemu, Wget
from lisa.tools.df import Df, PartitionInfo
from lisa.util import LisaException, SkippedException

NESTED_VM_IMAGE_NAME = "image.qcow2"
NESTED_VM_TEST_FILE_NAME = "message.txt"
NESTED_VM_TEST_FILE_CONTENT = "Message from L1 vm!!"
NESTED_VM_TEST_PUBLIC_FILE_URL = "http://www.github.com"
NESTED_VM_REQUIRED_DISK_SIZE_IN_GB = 6


def connect_nested_vm(
    host: RemoteNode,
    guest_username: str,
    guest_password: str,
    guest_port: int,
    guest_image_url: str,
    image_name: str = NESTED_VM_IMAGE_NAME,
    image_size: int = NESTED_VM_REQUIRED_DISK_SIZE_IN_GB,
    disks: Optional[List[str]] = None,
) -> RemoteNode:

    # verify that virtualization is enabled in hardware
    is_virtualization_enabled = host.tools[Lscpu].is_virtualization_enabled()
    if not is_virtualization_enabled:
        raise SkippedException("Virtualization is not enabled in hardware")

    # verify os compatibility
    if not (
        isinstance(host.os, Debian)
        or isinstance(host.os, Fedora)
        or isinstance(host.os, Suse)
    ):
        raise SkippedException(
            f"{host.os} is not supported. Currently the test could be "
            "run on Debian, Fedora and Suse distros."
        )

    image_folder_path = find_partition_with_freespace(host, image_size)

    host.tools[Wget].get(
        url=guest_image_url,
        file_path=image_folder_path,
        filename=image_name,
        sudo=True,
    )

    # start nested vm
    host.tools[Qemu].create_vm(guest_port, f"{image_folder_path}/{image_name}", disks)

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


def find_partition_with_freespace(node: RemoteNode, size_in_gb: int) -> str:
    df = node.tools[Df]
    home_partition = df.get_partition_by_mountpoint("/home")
    if home_partition and _is_partition_capable(home_partition, size_in_gb):
        return home_partition.mountpoint

    mnt_partition = df.get_partition_by_mountpoint("/mnt")
    if mnt_partition and _is_partition_capable(mnt_partition, size_in_gb):
        return mnt_partition.mountpoint

    raise LisaException(
        f"No partition with Required disk space of {size_in_gb}GB found"
    )


def parse_nested_image_variables(
    variables: Dict[str, Any]
) -> Tuple[str, str, int, str]:
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

    return (
        nested_image_username,
        nested_image_password,
        nested_image_port,
        nested_image_url,
    )


def _is_partition_capable(
    partition: PartitionInfo,
    size: int,
) -> bool:
    # check if the partition has enough space to download nested image file
    unused_partition_size_in_gb = (partition.total_blocks - partition.used_blocks) / (
        1024 * 1024
    )
    if unused_partition_size_in_gb > size:
        return True

    return False
