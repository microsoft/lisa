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
class AutoDetectIdentifier:
    # Auto-detect suitable NICs for passthrough.
    # When enabled, LISA will automatically select NICs that:
    # - Have an IOMMU group (required for VFIO passthrough)
    # - Are not the default route interface (management NIC)
    # - Have link up (mandatory)
    # SR-IOV capability is NOT required — physical NICs are passed through
    # directly and do not need to support virtual functions.
    enabled: bool = True
    # Number of NICs to detect. 0 (default) means detect ALL suitable NICs so
    # the pool is fully populated and can satisfy any number of concurrent nodes.
    count: int = 0
    vendor_id: str = ""  # Optional: filter by vendor ID
    device_id: str = ""  # Optional: filter by device ID


# Configuration options for device-passthrough for the VM.
@dataclass_json()
@dataclass
class HostDevicePoolSchema:
    type: HostDevicePoolType = HostDevicePoolType.PCI_NIC
    devices: Union[
        List[VendorDeviceIdIdentifier], PciAddressIdentifier, AutoDetectIdentifier
    ] = field(default_factory=lambda: cast(List[VendorDeviceIdIdentifier], []))


@dataclass_json()
@dataclass
class DevicePassthroughSchema:
    pool_type: HostDevicePoolType = HostDevicePoolType.PCI_NIC
    count: int = 0
