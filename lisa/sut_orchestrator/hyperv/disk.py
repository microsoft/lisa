# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List

from lisa import features

from .context import get_node_context


class Disk(features.Disk):
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        node_context = get_node_context(self._node)
        _vm_name = node_context.vm_name
        _server = node_context.host

    def get_all_disks(
        self,
    ) -> List[str]:
        raise NotImplementedError
