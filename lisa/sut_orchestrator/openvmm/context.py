# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass
from typing import Optional

from lisa.node import Node


@dataclass
class NodeContext:
    vm_name: str = ""
    host: Optional[Node] = None
    working_path: str = ""
    uefi_firmware_path: str = ""
    disk_img_path: str = ""
    console_log_file_path: str = ""
    launcher_log_file_path: str = ""
    guest_address: str = ""
    ssh_port: int = 22
    forwarded_port: int = 0
    forwarding_enabled: bool = False
    forwarding_interface: str = ""
    tap_created: bool = False
    tap_bridge_created: bool = False
    tap_dnsmasq_pid_file: str = ""
    tap_dnsmasq_lease_file: str = ""
    process_id: str = ""
    command_line: str = ""


def get_node_context(node: Node) -> NodeContext:
    return node.get_context(NodeContext)
