# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import TYPE_CHECKING

from .kill import Kill

if TYPE_CHECKING:
    from lisa.node import Node


class KillableMixin:
    def kill(self, process_name: str = "") -> None:
        # make sure this Mixin used with Tool.
        node: Node = self.node  # type: ignore
        if not process_name:
            process_name = self.command  # type: ignore
        kill_tool = node.tools[Kill]
        kill_tool.by_name(process_name)
