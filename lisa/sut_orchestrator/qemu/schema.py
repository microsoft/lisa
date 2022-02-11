from dataclasses import dataclass
from typing import Optional

from dataclasses_json import dataclass_json

FIRMWARE_TYPE_BIOS = "bios"
FIRMWARE_TYPE_UEFI = "uefi"


# Configuration options for cloud-init ISO generation for the VM.
@dataclass_json()
@dataclass
class CloudInitSchema:
    # Additional values to apply to the cloud-init user-data file.
    extra_user_data: Optional[str] = None


# QEMU orchestrator's global configuration options.
@dataclass_json()
@dataclass
class QemuPlatformSchema:
    # The timeout length for how long to wait for the OS to boot and request an IP
    # address from the libvirt DHCP server.
    # Specified in seconds. Default: 30s.
    network_boot_timeout: Optional[float] = None


# QEMU orchestrator's per-node configuration options.
@dataclass_json()
@dataclass
class QemuNodeSchema:
    # The disk image to use for the node.
    # The file must use the qcow2 file format and should not be changed during test
    # execution.
    qcow2: str = ""
    # Configuration options for cloud-init.
    cloud_init: Optional[CloudInitSchema] = None
    # Whether to use UEFI or BIOS firmware.
    # Defaults to UEFI.
    firmware_type: str = ""
