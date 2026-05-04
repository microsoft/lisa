# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, List, Optional

from lisa.node import Node
from lisa.util import LisaException


@dataclass
class NodeContext:
    vm_name: str = ""
    host: Optional[Node] = None
    working_path: str = ""
    uefi_firmware_path: str = ""
    disk_img_path: str = ""
    cloud_init_file_path: str = ""
    console_log_file_path: str = ""
    launcher_log_file_path: str = ""
    launcher_stderr_log_file_path: str = ""
    extra_cloud_init_user_data: List[Dict[str, Any]] = field(default_factory=list)
    guest_address: str = ""
    ssh_port: int = 22
    forwarded_port: int = 0
    forwarding_enabled: bool = False
    forwarding_interface: str = ""
    tap_created: bool = False
    tap_bridge_created: bool = False
    tap_bridge_netfilter_disabled: bool = False
    tap_dhcp_input_rule_added: bool = False
    tap_input_rules_added: List[str] = field(default_factory=list)
    tap_dnsmasq_pid_file: str = ""
    tap_dnsmasq_lease_file: str = ""
    effective_network: Optional[Any] = None
    process_id: str = ""
    command_line: str = ""


@dataclass
class OpenVmmHostContext:
    original_ip_forward_value: str = ""
    active_forwarding_count: int = 0
    original_bridge_netfilter_values: Dict[str, str] = field(default_factory=dict)
    active_bridge_netfilter_count: int = 0
    artifact_copy_lock: Lock = field(default_factory=Lock)


def get_node_context(node: Node) -> NodeContext:
    return node.get_context(NodeContext)


def get_host_context(node: Node) -> OpenVmmHostContext:
    context_attr = "_openvmm_host_context"
    if not hasattr(node, context_attr):
        setattr(node, context_attr, OpenVmmHostContext())

    context = getattr(node, context_attr)
    if not isinstance(context, OpenVmmHostContext):
        raise LisaException(
            "unexpected OpenVMM host context type "
            f"'{type(context).__name__}' stored in '{context_attr}'. Clear "
            "the stale attribute or ensure only OpenVMM stores "
            "OpenVmmHostContext in this slot."
        )
    return context
