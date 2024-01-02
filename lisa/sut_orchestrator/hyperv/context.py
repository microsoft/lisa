from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

from lisa import Node


@dataclass
class NodeContext:
    vm_name: str = ""
    vhd_local_path = PurePosixPath()  # Local path on the machine where LISA is running
    vhd_remote_path = PureWindowsPath()  # Path on the hyperv server
    console_log_path = PureWindowsPath()  # Remote path with serial console output


def get_node_context(node: Node) -> NodeContext:
    return node.get_context(NodeContext)
