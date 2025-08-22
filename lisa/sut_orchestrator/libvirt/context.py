from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import libvirt

from lisa.environment import Environment
from lisa.node import Node
from lisa.sut_orchestrator.util.schema import HostDevicePoolType

from .console_logger import QemuConsoleLogger
from .schema import DeviceAddressSchema, DiskImageFormat


@dataclass
class DataDiskContext:
    file_path: str = ""
    size_gib: int = 0


@dataclass
class EnvironmentContext:
    ssh_public_key: str = ""

    # Timeout for the OS to boot and acquire an IP address, in seconds.
    network_boot_timeout: float = 30.0

    # List of (port, IP) used in port forwading
    port_forwarding_list: List[Tuple[int, str]] = field(default_factory=list)


@dataclass
class InitSystem:
    CLOUD_INIT: str = "cloud-init"
    IGNITION: str = "ignition"


@dataclass
class DevicePassthroughContext:
    pool_type: HostDevicePoolType = HostDevicePoolType.PCI_NIC
    device_list: List[DeviceAddressSchema] = field(
        default_factory=list,
    )
    managed: str = ""


@dataclass
class GuestVmType(Enum):
    Standard = "Standard"
    ConfidentialVM = "ConfidentialVM"


@dataclass
class NodeContext:
    vm_name: str = ""
    kernel_source_path: str = ""
    kernel_path: str = ""
    host_data: str = ""
    is_host_data_base64: bool = False
    guest_vm_type: GuestVmType = field(default_factory=lambda: GuestVmType.Standard)
    cloud_init_file_path: str = ""
    ignition_file_path: str = ""
    os_disk_source_file_path: Optional[str] = None
    os_disk_base_file_path: str = ""
    os_disk_base_file_fmt: DiskImageFormat = DiskImageFormat.QCOW2
    os_disk_file_path: str = ""
    os_disk_img_resize_gib: Optional[int] = None
    console_log_file_path: str = ""
    extra_cloud_init_user_data: List[Dict[str, Any]] = field(default_factory=list)
    use_bios_firmware: bool = False
    data_disks: List[DataDiskContext] = field(default_factory=list)
    next_disk_index: int = 0
    machine_type: Optional[str] = None
    enable_secure_boot: bool = False
    init_system: str = InitSystem.CLOUD_INIT

    console_logger: Optional[QemuConsoleLogger] = None
    domain: Optional[libvirt.virDomain] = None

    # Device pass through configuration
    passthrough_devices: List[DevicePassthroughContext] = field(
        default_factory=list,
    )


def get_environment_context(environment: Environment) -> EnvironmentContext:
    return environment.get_context(EnvironmentContext)


def get_node_context(node: Node) -> NodeContext:
    return node.get_context(NodeContext)
