# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import io
import ipaddress
import re
import secrets
import string
import time
from typing import Any, Dict, List, Optional, Tuple

import paramiko
import pycdlib
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
_DEFAULT_NESTED_USERNAME = "lisauser"
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
    cmd_result = host.execute(
        f"openssl passwd -6 {password}",
        sudo=True,
        shell=True,
    )
    # The expected exit code is 0, indicating success.
    # If a non-zero exit code is encountered, try using the -1 option.
    # Note: The -6 option may not be available in older versions.
    # Output:
    #     Usage: passwd [options] [passwords]
    # where options are
    # -crypt             standard Unix password algorithm (default)
    # -1                 MD5-based password algorithm
    # -apr1              MD5-based password algorithm, Apache variant
    # -salt string       use provided salt
    # -in file           read passwords from file
    # -stdin             read passwords from stdin
    # -noverify          never verify when reading password from terminal
    # -quiet             no warnings
    # -table             format output as table
    # -reverse           switch table columns
    if cmd_result.exit_code != 0:
        cmd_result = host.execute(
            f"openssl passwd -1 {password}",
            sudo=True,
            shell=True,
        )
    if cmd_result.exit_code != 0:
        raise LisaException("fail to run openssl command to convert password")
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
        "growpart": {
            "mode": "auto",
            "devices": ["/dev/sda1"],
            "fixup_filesystem": True,
        },
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


def _is_ipv6_address(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).version == 6
    except ValueError:
        return False


def _open_host_loopback_channel(
    jump_client: paramiko.SSHClient, guest_port: int
) -> Any:
    transport = jump_client.get_transport()
    assert transport
    return transport.open_channel(
        kind="direct-tcpip",
        src_addr=("127.0.0.1", 0),
        dest_addr=("127.0.0.1", guest_port),
    )


def _wait_nested_ssh_via_host(
    host_jump_box: schema.ConnectionInfo,
    connection_info: schema.ConnectionInfo,
    guest_port: int,
    timeout: int = 300,
) -> None:
    # QEMU forwards the nested vm's SSH port on the host loopback only, so reach
    # it by tunneling through the host as an SSH jump box. A fresh direct-tcpip
    # channel is opened for each attempt while the nested vm boots.
    jump_client = paramiko.SSHClient()
    jump_client.set_missing_host_key_policy(paramiko.MissingHostKeyPolicy())
    jump_client.connect(
        hostname=host_jump_box.address,
        port=host_jump_box.port,
        username=host_jump_box.username,
        password=host_jump_box.password,
        key_filename=host_jump_box.private_key_file,
        banner_timeout=10,
    )
    try:
        deadline = time.time() + timeout
        last_error: Optional[Exception] = None
        while time.time() < deadline:
            try:
                try_connect(
                    connection_info,
                    ssh_timeout=30,
                    sock_factory=lambda: _open_host_loopback_channel(
                        jump_client, guest_port
                    ),
                )
                return
            except Exception as e:
                last_error = e
                time.sleep(5)
        raise LisaException(
            "nested vm ssh connection cannot be established through host "
            f"tunnel: {last_error}"
        )
    finally:
        jump_client.close()


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
    # QEMU user-mode networking forwards the nested vm's SSH port on the host
    # with `hostfwd=tcp::<port>-:22`, which binds IPv4 (0.0.0.0) only. When LISA
    # reaches the host over IPv6 (use_ipv6), a direct connection to
    # [host_ipv6]:<port> has nothing listening. To make nested tests pass over
    # both IPv4 and IPv6, when the host is reached over IPv6 tunnel to the host
    # loopback (127.0.0.1:<port>, always covered by 0.0.0.0) through the host
    # itself as an SSH jump box.
    host_connection = host.connection_info
    host_address = host_connection["address"]

    host_jump_box: Optional[schema.ConnectionInfo] = None
    proxy_jump_boxes: Optional[List[schema.ConnectionInfo]] = None
    if _is_ipv6_address(host_address):
        host_jump_box = schema.ConnectionInfo(**host_connection)
        proxy_jump_boxes = [host_jump_box]
        nested_address = "127.0.0.1"
    else:
        nested_address = host_address

    connection_info = schema.ConnectionInfo(
        address=nested_address,
        port=guest_port,
        username=guest_username,
        password=guest_password,
    )

    nested_vm = RemoteNode(Node(name=name), 0, name)
    nested_vm.set_connection_info(
        public_port=guest_port,
        proxy_jump_boxes=proxy_jump_boxes,
        **fields_to_dict(connection_info, ["address", "port", "username", "password"]),
    )

    # wait for nested vm ssh connection to be ready
    if host_jump_box is not None:
        _wait_nested_ssh_via_host(host_jump_box, connection_info, guest_port)
    else:
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
    host_address = host.connection_info["address"]
    connection_info = schema.ConnectionInfo(
        address=host_address,
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


def _generate_password(length: int = 16) -> str:
    upper = string.ascii_uppercase
    lower = string.ascii_lowercase
    digits = string.digits
    # Exclude shell metacharacters ('$', '&') that would be interpreted
    # when the password is passed to `openssl passwd` via shell=True.
    special = "!@#%*"
    pool = upper + lower + digits + special
    while True:
        pwd = [
            secrets.choice(upper),
            secrets.choice(lower),
            secrets.choice(digits),
            secrets.choice(special),
        ]
        pwd += [secrets.choice(pool) for _ in range(length - 4)]
        secrets.SystemRandom().shuffle(pwd)
        result = "".join(pwd)
        if (
            any(c in upper for c in result)
            and any(c in lower for c in result)
            and any(c in digits for c in result)
            and any(c in special for c in result)
        ):
            return result


def parse_nested_image_variables(
    variables: Dict[str, Any],
) -> Tuple[str, str, int, str]:
    nested_image_username = variables.get("nested_image_username", "")
    nested_image_password = variables.get("nested_image_password", "")
    nested_image_port = 60024
    nested_image_url = variables.get("nested_image_url", "")

    if not nested_image_username:
        nested_image_username = _DEFAULT_NESTED_USERNAME

    if not nested_image_password:
        nested_image_password = _generate_password()

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
