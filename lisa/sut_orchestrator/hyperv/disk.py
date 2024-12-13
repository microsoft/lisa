# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List

from lisa import features

from .context import get_node_context


class Disk(features.Disk, node: Node):
    def __init__(self, node: RemoteNode) -> None:
        node_context = get_node_context(node)
        self._vm_name = node_context.vm_name

        node_context = get_node_context(node)
        node_context.vm_name = vm_name
        node_context.host = self._server

    def get_all_disks(
        self,
    ) -> List[str]:
        raise NotImplementedError
