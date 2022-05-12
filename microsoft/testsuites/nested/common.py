# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict, List, Optional, Tuple

from lisa import RemoteNode
from lisa.features.network_interface import Synthetic
from lisa.operating_system import Debian, Fedora, Suse
from lisa.schema import Node
from lisa.tools import HyperV, Lscpu, Qemu, Wget
from lisa.tools.rm import Rm
from lisa.util import SkippedException, fields_to_dict
from lisa.util.logger import Logger
from lisa.util.shell import ConnectionInfo, try_connect

QEMU_NESTED_VM_IMAGE_NAME = "image.qcow2"
HYPERV_NESTED_VM_IMAGE_NAME = "image.vhdx"
HYPERV_NAT_NAME = "nestedvmnat"
HYPER_IMAGE_FOLDER = "C:\\lisaimages"
NESTED_VM_TEST_FILE_NAME = "message.txt"
NESTED_VM_TEST_FILE_CONTENT = "Message from L1 vm!!"
NESTED_VM_TEST_PUBLIC_FILE_URL = "http://www.github.com"
NESTED_VM_REQUIRED_DISK_SIZE_IN_GB = 6
NESTED_VM_DOWNLOAD_TIMEOUT = 3600


def qemu_connect_nested_vm(
    host: RemoteNode,
    guest_username: str,
    guest_password: str,
    guest_port: int,
    guest_image_url: str,
    name: str = "L2-VM",
    image_name: str = QEMU_NESTED_VM_IMAGE_NAME,
    image_size: int = NESTED_VM_REQUIRED_DISK_SIZE_IN_GB,
    nic_model: str = "e1000",
    taps: int = 0,
    cores: int = 2,
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
        timeout=NESTED_VM_DOWNLOAD_TIMEOUT,
    )

    # start nested vm
    host.tools[Qemu].create_vm(
        guest_port,
        f"{image_folder_path}/{image_name}",
        nic_model=nic_model,
        taps=taps,
        bridge=bridge,
        disks=disks,
        cores=cores,
        stop_existing_vm=stop_existing_vm,
    )

    # setup connection to nested vm
    connection_info = ConnectionInfo(
        address=host.public_address,
        port=guest_port,
        username=guest_username,
        password=guest_password,
    )

    nested_vm = RemoteNode(Node(name=name), 0, name)
    nested_vm.set_connection_info(
        public_port=guest_port,
        **fields_to_dict(connection_info, ["address", "port", "username", "password"]),
    )

    # wait for nested vm ssh connection to be ready
    try_connect(connection_info)

    return nested_vm


def hyperv_connect_nested_vm(
    host: RemoteNode,
    guest_username: str,
    guest_password: str,
    port: int,
    guest_image_url: str,
    name: str = "l2_vm",
    image_name: str = HYPERV_NESTED_VM_IMAGE_NAME,
    switch_name: str = "nestedvmswitch",
    nat_name: str = HYPERV_NAT_NAME,
) -> RemoteNode:
    # delete vm if it exists, otherwise it will fail to delete
    # any present images
    hyperv = host.tools[HyperV]
    hyperv.delete_vm(name)

    # Download nested vm image
    image_name = f"{name}_{image_name}"
    file_path = host.tools[Wget].get(
        guest_image_url,
        HYPER_IMAGE_FOLDER,
        image_name,
    )

    # setup NAT
    hyperv.setup_nat_networking(switch_name, nat_name)
    hyperv.create_vm(
        name,
        file_path,
        switch_name,
    )

    # cleanup all existing port forwarding rules and
    # enable port forwarding for the nested vm
    local_ip = hyperv.get_ip_address(name)
    hyperv.delete_port_forwarding(nat_name)
    hyperv.setup_port_forwarding(nat_name, port, local_ip)

    # setup connection to nested vm
    connection_info = ConnectionInfo(
        address=host.public_address,
        port=port,
        username=guest_username,
        password=guest_password,
    )

    nested_vm = RemoteNode(Node(name=name), 0, name)
    nested_vm.set_connection_info(
        **fields_to_dict(connection_info, ["address", "port", "username", "password"])
    )
    nested_vm.capability.network_interface = Synthetic()

    # wait for nested vm ssh connection to be ready
    try_connect(connection_info)

    return nested_vm


def hyperv_remove_nested_vm(
    host: RemoteNode,
    name: str = "L2-VM",
    image_name: str = HYPERV_NESTED_VM_IMAGE_NAME,
    switch_name: str = "nestedvmswitch",
    nat_name: str = "nestedvmnat",
) -> None:
    image_name = f"{name}_{image_name}"
    file_path = f"{HYPER_IMAGE_FOLDER}\\{image_name}"
    hyperv = host.tools[HyperV]

    # Delete VM
    hyperv.delete_vm(name)

    # delete image
    host.tools[Rm].remove_file(file_path)

    # delete nat network
    hyperv.delete_nat_networking(switch_name, nat_name)

    # enable port forwarding
    hyperv.delete_port_forwarding(nat_name)


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
