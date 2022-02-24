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

@dataclass_json()
@dataclass
class LibvirtHost:
    address: Optional[str] = None
    username: Optional[str] = None
    private_key_file: Optional[str] = None

    # The directory where lisa will store VM related files (such as disk images).
    # This directory must already exist and the test user should have write permission
    # to it.
    lisa_working_dir: Optional[str] = "/var/tmp"

# QEMU orchestrator's global configuration options.
@dataclass_json()
@dataclass
class QemuPlatformSchema:
    # An optional remote host for the VMs. All test VMs will be spawned on the
    # specified host by connecting remotely to the libvirt instance running on it.
    # If None, the local machine is used as host.
    host: Optional[LibvirtHost] = LibvirtHost()

    # The timeout length for how long to wait for the OS to boot and request an IP
    # address from the libvirt DHCP server.
    # Specified in seconds. Default: 30s.
    network_boot_timeout: Optional[float] = None

    def is_host_remote(self) -> bool:
        return self.host.address is not None


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
