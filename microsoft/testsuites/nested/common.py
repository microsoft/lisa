# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict, List, Optional, Tuple

from lisa import RemoteNode
from lisa.operating_system import Debian, Fedora, Suse
from lisa.schema import Node
from lisa.tools import Lscpu, Qemu, Wget
from lisa.util import SkippedException
from lisa.util.logger import Logger
from lisa.util.shell import ConnectionInfo, try_connect

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
    name: str = "L2-VM",
    image_name: str = NESTED_VM_IMAGE_NAME,
    image_size: int = NESTED_VM_REQUIRED_DISK_SIZE_IN_GB,
    nic_model: str = "e1000",
    taps: int = 0,
    bridge: Optional[str] = None,
    disks: Optional[List[str]] = None,
    stop_existing_vm: bool = True,
    log: Optional[Logger] = None,
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

    image_folder_path = host.find_partition_with_freespace(image_size)

    host.tools[Wget].get(
        url=guest_image_url,
        file_path=image_folder_path,
        filename=image_name,
        sudo=True,
    )

    # start nested vm
    host.tools[Qemu].create_vm(
        guest_port,
        f"{image_folder_path}/{image_name}",
        nic_model=nic_model,
        taps=taps,
        bridge=bridge,
        disks=disks,
        stop_existing_vm=stop_existing_vm,
    )

    # setup connection to nested vm
    nested_vm = RemoteNode(Node(name=name), 0, name)
    nested_vm.set_connection_info(
        public_address=host.public_address,
        username=guest_username,
        password=guest_password,
        public_port=guest_port,
        port=guest_port,
    )

    # wait for nested vm ssh connection to be ready
    try_connect(
        ConnectionInfo(
            address=host.public_address,
            port=guest_port,
            username=guest_username,
            password=guest_password,
        )
    )

    return nested_vm


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
