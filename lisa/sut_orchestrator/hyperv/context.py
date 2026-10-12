# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, ClassVar, Dict, List, Mapping, Optional

from lisa import LisaException, Node, RemoteNode
from lisa.sut_orchestrator.hyperv.schema import DeviceAddressSchema
from lisa.sut_orchestrator.util.schema import HostDevicePoolType
from lisa.util.process import Process


@dataclass(frozen=True)
class NvmeDiskState:
    number: int
    unique_id: str
    serial_number: str
    was_offline: bool


@dataclass(frozen=True)
class HyperVNvmeRecoveryState:
    CURRENT_SCHEMA_VERSION: ClassVar[int] = 1

    schema_version: int
    location_path: str
    instance_id: str
    disk: NvmeDiskState

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema_version": self.schema_version,
                "location_path": self.location_path,
                "instance_id": self.instance_id,
                "disk": {
                    "number": self.disk.number,
                    "unique_id": self.disk.unique_id,
                    "serial_number": self.disk.serial_number,
                    "was_offline": self.disk.was_offline,
                },
            },
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, value: str) -> "HyperVNvmeRecoveryState":
        try:
            raw_state = json.loads(value)
        except (TypeError, json.JSONDecodeError) as err:
            raise LisaException("Invalid Hyper-V NVMe recovery state JSON") from err
        if not isinstance(raw_state, dict):
            raise LisaException("Hyper-V NVMe recovery state must be a JSON object")
        return cls.from_dict(raw_state)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HyperVNvmeRecoveryState":
        expected_keys = {"schema_version", "location_path", "instance_id", "disk"}
        if set(value) != expected_keys:
            raise LisaException(
                "Hyper-V NVMe recovery state properties do not match schema"
            )

        schema_version = value["schema_version"]
        if (
            type(schema_version) is not int
            or schema_version != cls.CURRENT_SCHEMA_VERSION
        ):
            raise LisaException(
                f"Unsupported Hyper-V NVMe recovery state schema version "
                f"'{schema_version}'"
            )

        location_path = value["location_path"]
        instance_id = value["instance_id"]
        if not isinstance(location_path, str) or not location_path.strip():
            raise LisaException(
                "Hyper-V NVMe recovery state location_path must be a string"
            )
        if not isinstance(instance_id, str) or not instance_id.strip():
            raise LisaException(
                "Hyper-V NVMe recovery state instance_id must be a string"
            )

        raw_disk = value["disk"]
        disk_keys = {"number", "unique_id", "serial_number", "was_offline"}
        if not isinstance(raw_disk, dict) or set(raw_disk) != disk_keys:
            raise LisaException(
                "Hyper-V NVMe recovery disk properties do not match schema"
            )
        number = raw_disk["number"]
        unique_id = raw_disk["unique_id"]
        serial_number = raw_disk["serial_number"]
        was_offline = raw_disk["was_offline"]
        if type(number) is not int or number < 0:
            raise LisaException(
                "Hyper-V NVMe recovery disk number must be a non-negative integer"
            )
        if not isinstance(unique_id, str) or not isinstance(serial_number, str):
            raise LisaException("Hyper-V NVMe recovery disk identities must be strings")
        if not unique_id.strip() and not serial_number.strip():
            raise LisaException(
                "Hyper-V NVMe recovery disk must have a stable identity"
            )
        if type(was_offline) is not bool:
            raise LisaException(
                "Hyper-V NVMe recovery disk was_offline must be a boolean"
            )

        return cls(
            schema_version=schema_version,
            location_path=location_path.strip(),
            instance_id=instance_id.strip(),
            disk=NvmeDiskState(
                number=number,
                unique_id=unique_id.strip(),
                serial_number=serial_number.strip(),
                was_offline=was_offline,
            ),
        )


@dataclass
class DevicePassthroughContext:
    pool_type: HostDevicePoolType = HostDevicePoolType.PCI_NIC
    device_list: List[DeviceAddressSchema] = field(
        default_factory=list,
    )
    requested_count: int = 0
    nvme_disk_states: Dict[str, NvmeDiskState] = field(default_factory=dict)


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
