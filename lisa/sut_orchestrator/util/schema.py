from dataclasses import dataclass, field
from enum import Enum
from typing import List

from dataclasses_json import dataclass_json


class HostDevicePoolType(Enum):
    PCI_NIC = "pci_net"
    PCI_GPU = "pci_gpu"


@dataclass_json()
@dataclass
class DeviceIdentifier:
    vendor_id: str = ""
    device_id: str = ""


# Configuration options for device-passthrough for the VM.
@dataclass_json()
@dataclass
class HostDevicePoolSchema:
    type: HostDevicePoolType = HostDevicePoolType.PCI_NIC
    devices: List[DeviceIdentifier] = field(default_factory=list)


@dataclass_json()
@dataclass
class DevicePassthroughSchema:
    pool_type: HostDevicePoolType = HostDevicePoolType.PCI_NIC
    count: int = 0
