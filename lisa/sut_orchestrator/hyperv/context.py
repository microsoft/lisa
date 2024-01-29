# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Optional

from lisa import Node, RemoteNode
from lisa.util.parallel import TaskManager


@dataclass
class NodeContext:
    vm_name: str = ""
    host: Optional[RemoteNode] = None
    working_dir = PureWindowsPath()
    vhd_path = PureWindowsPath()
    serial_log_task_mgr: Optional["TaskManager[None]"] = None

    @property
    def console_log_path(self) -> PureWindowsPath:
        return self.working_dir / f"{self.vm_name}-console.log"


def get_node_context(node: Node) -> NodeContext:
    return node.get_context(NodeContext)
