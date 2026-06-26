# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, List, Optional

from lisa.node import Node
from lisa.sut_orchestrator.util.schema import HostDevicePoolType
from lisa.util import LisaException

from .schema import OpenVmmNetworkSchema


def _new_extra_cloud_init_user_data() -> List[Dict[str, Any]]:
    return []


def _new_str_list() -> List[str]:
    return []


def _new_str_dict() -> Dict[str, str]:
    return {}


@dataclass
class DeviceAddressSchema:
    domain: str = "0000"
    bus: str = ""
    slot: str = ""
    function: str = "0"


@dataclass
class DevicePassthroughContext:
    pool_type: HostDevicePoolType = HostDevicePoolType.PCI_NIC
    device_list: List[DeviceAddressSchema] = field(default_factory=list)
    managed: str = ""


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
    extra_cloud_init_user_data: List[Dict[str, Any]] = field(
        default_factory=_new_extra_cloud_init_user_data
    )
    guest_address: str = ""
    ssh_port: int = 22
    forwarded_port: int = 0
    forwarding_enabled: bool = False
    forwarding_interface: str = ""
    tap_created: bool = False
    tap_bridge_created: bool = False
    tap_bridge_netfilter_disabled: bool = False
    tap_input_rules_added: List[str] = field(default_factory=_new_str_list)
    tap_dnsmasq_pid_file: str = ""
    tap_dnsmasq_lease_file: str = ""
    effective_network: Optional[OpenVmmNetworkSchema] = None
    process_id: str = ""
    command_line: str = ""
    passthrough_devices: List[DevicePassthroughContext] = field(default_factory=list)


@dataclass
class OpenVmmHostContext:
    original_ip_forward_value: str = ""
    active_forwarding_count: int = 0
    original_bridge_netfilter_values: Dict[str, str] = field(
        default_factory=_new_str_dict
    )
    active_bridge_netfilter_count: int = 0
    artifact_copy_lock: Lock = field(default_factory=Lock)
    artifact_cache: Dict[str, str] = field(default_factory=_new_str_dict)
    device_pool_lock: Lock = field(default_factory=Lock)
    device_pool: Optional[Any] = None
    device_pool_config_key: str = ""


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
