from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from lisa.environment import Environment
from lisa.node import Node

from .console_logger import QemuConsoleLogger


@dataclass
class DataDiskContext:
    file_path: str = ""
    size_gib: int = 0


@dataclass
class EnvironmentContext:
    ssh_public_key: str = ""

    # Timeout for the OS to boot and acquire an IP address, in seconds.
    network_boot_timeout: float = 30.0


@dataclass
class NodeContext:
    vm_name: str = ""
    vm_disks_dir: str = ""
    cloud_init_file_path: str = ""
    os_disk_source_file_path: Optional[str] = None
    os_disk_base_file_path: str = ""
    os_disk_file_path: str = ""
    console_log_file_path: str = ""
    extra_cloud_init_user_data: List[Dict[str, Any]] = field(default_factory=list)
    console_logger: Optional[QemuConsoleLogger] = None
    use_bios_firmware: bool = False
    data_disks: List[DataDiskContext] = field(default_factory=list)
    next_disk_index: int = 0


def get_environment_context(environment: Environment) -> EnvironmentContext:
    return environment.get_context(EnvironmentContext)


def get_node_context(node: Node) -> NodeContext:
    return node.get_context(NodeContext)
