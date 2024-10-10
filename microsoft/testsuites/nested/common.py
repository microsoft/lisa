# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import io
import re
from typing import Any, Dict, List, Optional, Tuple

import pycdlib  # type: ignore
import yaml

from lisa import RemoteNode, schema
from lisa.features.network_interface import Synthetic
from lisa.operating_system import Debian, Fedora, Suse
from lisa.schema import Node
from lisa.tools import Aria, Dmesg, HyperV, Lscpu, Qemu, RemoteCopy, Wget
from lisa.tools.rm import Rm
from lisa.util import LisaException, SkippedException, fields_to_dict, get_matched_str
from lisa.util.logger import Logger
from lisa.util.shell import try_connect

QEMU_NESTED_VM_IMAGE_NAME = "image.qcow2"
HYPERV_NESTED_VM_IMAGE_NAME = "image.vhdx"
HYPERV_NAT_NAME = "nestedvmnat"
HYPER_IMAGE_FOLDER = "C:\\lisaimages"
NESTED_VM_TEST_FILE_NAME = "message.txt"
NESTED_VM_TEST_FILE_CONTENT = "Message from L1 vm!!"
NESTED_VM_TEST_PUBLIC_FILE_URL = "http://www.github.com"
NESTED_VM_REQUIRED_DISK_SIZE_IN_GB = 6
NESTED_VM_DOWNLOAD_TIMEOUT = 3600
KVM_CRASH_CALL_STACK_PATTERN = re.compile(
    r"KVM: accessing unsupported EVMCS field 2032", re.M
)


def _create_cloud_init_iso(
    host: RemoteNode,
    iso_file_name: str,
    user_name: str,
    password: str,
    host_name: str = "l2vm",
) -> str:
    cmd_result = host.execute(f"openssl passwd -6 {password}", sudo=True, shell=True)
    user_data = {
        "users": [
            "default",
            {
                "name": user_name,
                "shell": "/bin/bash",
                "sudo": ["ALL=(ALL) NOPASSWD:ALL"],
                "groups": ["sudo", "docker"],
                "passwd": cmd_result.stdout,
                "lock_passwd": False,
            },
        ],
        "ssh_pwauth": True,
    }
    meta_data = {
        "local-hostname": host_name,
    }

    user_data_string = "#cloud-config\n" + yaml.safe_dump(user_data)
    meta_data_string = yaml.safe_dump(meta_data)
    files = [("/user-data", user_data_string), ("/meta-data", meta_data_string)]
    iso = pycdlib.PyCdlib()
    iso.new(joliet=3, vol_ident="cidata")

    for i, file in enumerate(files):
        path, contents = file
        contents_data = contents.encode()
        iso.add_fp(
            io.BytesIO(contents_data),
            len(contents_data),
            f"/{i}.;1",
            joliet_path=path,
        )

    iso.write(host.local_working_path / iso_file_name)
    copy = host.tools[RemoteCopy]
    copy.copy_to_remote(host.local_working_path / iso_file_name, host.working_path)
    return str(host.working_path / iso_file_name)


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
    use_cloud_init: bool = True,
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

    host.tools[Aria].get(
        url=guest_image_url,
        file_path=image_folder_path,
        filename=image_name,
        sudo=True,
        timeout=NESTED_VM_DOWNLOAD_TIMEOUT,
    )

    cd_rom = ""
    if use_cloud_init:
        cd_rom = _create_cloud_init_iso(
            host, "cloud-init.iso", guest_username, guest_password
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
        cd_rom=cd_rom,
    )

    # check known issues before connecting to L2 vm
    # refer https://bugs.launchpad.net/ubuntu/+source/linux-azure/+bug/1950462
    dmesg = host.tools[Dmesg].get_output(force_run=True)
    if get_matched_str(dmesg, KVM_CRASH_CALL_STACK_PATTERN):
        raise LisaException(
            "KVM crash due to lack of patches mentioned in "
            "https://patchwork.ozlabs.org/project/ubuntu-kernel/list/?series=273492"
        )

    # setup connection to nested vm
    connection_info = schema.ConnectionInfo(
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
    connection_info = schema.ConnectionInfo(
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
        nested_image_url = (
            "https://cloud-images.ubuntu.com/jammy/current/"
            "jammy-server-cloudimg-amd64.img"
        )

    return (
        nested_image_username,
        nested_image_password,
        nested_image_port,
        nested_image_url,
    )
