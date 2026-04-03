from dataclasses import dataclass, field
from enum import Enum
from typing import List, Union, cast

from dataclasses_json import dataclass_json


class HostDevicePoolType(Enum):
    PCI_NIC = "pci_net"
    PCI_GPU = "pci_gpu"


@dataclass_json()
@dataclass
class VendorDeviceIdIdentifier:
    vendor_id: str = ""
    device_id: str = ""


@dataclass_json()
@dataclass
class PciAddressIdentifier:
    # list of bdf like 0000:3b:00.0 - <domain>:<bus>:<slot>.<fn>
    pci_bdf: List[str] = field(default_factory=list)


@dataclass_json()
@dataclass
class DeviceLocationPathIdentifier:
    # List of Hyper-V DDA location paths like PCIROOT(20)#PCI(0300)#PCI(0000)
    location_path: List[str] = field(default_factory=list)


# Configuration options for device-passthrough for the VM.
@dataclass_json()
@dataclass
class HostDevicePoolSchema:
    type: HostDevicePoolType = HostDevicePoolType.PCI_NIC
    devices: Union[
        List[VendorDeviceIdIdentifier],
        PciAddressIdentifier,
        DeviceLocationPathIdentifier,
    ] = field(default_factory=lambda: cast(List[VendorDeviceIdIdentifier], []))


@dataclass_json()
@dataclass
class DevicePassthroughSchema:
    pool_type: HostDevicePoolType = HostDevicePoolType.PCI_NIC
    count: int = 0
