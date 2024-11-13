# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from pathlib import PurePath
from typing import List, Optional

from lisa import Node, RemoteNode
from lisa.sut_orchestrator.hyperv.schema import DeviceAddressSchema
from lisa.sut_orchestrator.util.schema import HostDevicePoolType
from lisa.util.process import Process


@dataclass
class DevicePassthroughContext:
    pool_type: HostDevicePoolType = HostDevicePoolType.PCI_NIC
    device_list: List[DeviceAddressSchema] = field(
        default_factory=list,
    )


@dataclass
class NodeContext:
    vm_name: str = ""
    host: Optional[RemoteNode] = None
    working_path = PurePath()
    serial_log_process: Optional[Process] = None

    # Device pass through configuration
    passthrough_devices: List[DevicePassthroughContext] = field(
        default_factory=list,
    )

    @property
    def console_log_path(self) -> PurePath:
        return self.working_path / f"{self.vm_name}-console.log"


def get_node_context(node: Node) -> NodeContext:
    return node.get_context(NodeContext)
