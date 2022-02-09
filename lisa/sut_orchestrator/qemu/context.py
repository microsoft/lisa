from dataclasses import dataclass
from typing import Any, Dict, Optional

from lisa.environment import Environment
from lisa.node import Node

from .console_logger import QemuConsoleLogger


@dataclass
class EnvironmentContext:
    ssh_public_key: str = ""


@dataclass
class NodeContext:
    vm_name: str = ""
    cloud_init_file_path: str = ""
    os_disk_base_file_path: str = ""
    os_disk_file_path: str = ""
    console_log_file_path: str = ""
    extra_cloud_init_user_data: Optional[Dict[str, Any]] = None
    console_logger: Optional[QemuConsoleLogger] = None
    use_bios_firmware: bool = False


def get_environment_context(environment: Environment) -> EnvironmentContext:
    return environment.get_context(EnvironmentContext)


def get_node_context(node: Node) -> NodeContext:
    return node.get_context(NodeContext)
