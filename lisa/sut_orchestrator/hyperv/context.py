# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Optional

from lisa import Node, RemoteNode
from lisa.util.parallel import TaskManager


@dataclass
class NodeContext:
    vm_name: str = ""
    host: Optional[RemoteNode] = None
    vhd_local_path = PurePosixPath()  # Local path on the machine where LISA is running
    vhd_remote_path = PureWindowsPath()  # Path on the hyperv server
    console_log_path = PureWindowsPath()  # Remote path with serial console output
    serial_log_task_mgr: Optional["TaskManager[None]"] = None


def get_node_context(node: Node) -> NodeContext:
    return node.get_context(NodeContext)
