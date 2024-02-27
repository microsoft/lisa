# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass
from pathlib import PurePath
from typing import Optional

from lisa import Node, RemoteNode
from lisa.util.process import Process


@dataclass
class NodeContext:
    vm_name: str = ""
    host: Optional[RemoteNode] = None
    working_path = PurePath()
    serial_log_process: Optional[Process] = None

    @property
    def console_log_path(self) -> PurePath:
        return self.working_path / f"{self.vm_name}-console.log"


def get_node_context(node: Node) -> NodeContext:
    return node.get_context(NodeContext)
