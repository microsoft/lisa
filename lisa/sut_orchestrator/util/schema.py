from dataclasses import dataclass
from enum import Enum

from dataclasses_json import dataclass_json


class HostDevicePoolType(Enum):
    PCI_NIC = "pci_net"
    PCI_GPU = "pci_gpu"


# Configuration options for device-passthrough for the VM.
@dataclass_json()
@dataclass
class HostDevicePoolSchema:
    type: HostDevicePoolType = HostDevicePoolType.PCI_NIC
    vendor_id: str = ""
    device_id: str = ""
