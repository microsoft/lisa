from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Union

from dataclasses_json import dataclass_json

from lisa.sut_orchestrator.util.schema import (
    DevicePassthroughSchema,
    HostDevicePoolSchema,
)
from lisa.util import LisaException

FIRMWARE_TYPE_BIOS = "bios"
FIRMWARE_TYPE_UEFI = "uefi"


# Configuration options for cloud-init ISO generation for the VM.
@dataclass_json()
@dataclass
class CloudInitSchema:
    # Additional values to apply to the cloud-init user-data file.
    extra_user_data: Optional[Union[str, List[str]]] = None


@dataclass_json()
@dataclass
class LibvirtHost:
    address: Optional[str] = None
    username: Optional[str] = None
    private_key_file: Optional[str] = None

    # The directory where lisa will store VM related files (such as disk images).
    # This directory must already exist and the test user should have write permission
    # to it.
    lisa_working_dir: str = "/var/tmp"

    def is_remote(self) -> bool:
        return self.address is not None


@dataclass_json()
@dataclass
class DeviceAddressSchema:
    # Host device details for which we want to perform device-passthrough
    # we can get it using lspci command
    domain: str = ""
    bus: str = ""
    slot: str = ""
    function: str = ""


# QEMU orchestrator's global configuration options.
@dataclass_json()
@dataclass
class BaseLibvirtPlatformSchema:
    # An optional remote host for the VMs. All test VMs will be spawned on the
    # specified host by connecting remotely to the libvirt instance running on it.
    #
    # CAUTION: Even though this field is a List, only one host is supported currently.
    hosts: List[LibvirtHost] = field(default_factory=lambda: [LibvirtHost()])

    # The timeout length for how long to wait for the OS to boot and request an IP
    # address from the libvirt DHCP server.
    # Specified in seconds. Default: 30s.
    network_boot_timeout: Optional[float] = None

    capture_libvirt_debug_logs: bool = False

    device_pools: Optional[List[HostDevicePoolSchema]] = None


@dataclass_json()
@dataclass
class LibvirtDevicePassthroughSchema(DevicePassthroughSchema):
    managed: str = ""


# Possible disk image formats
class DiskImageFormat(Enum):
    QCOW2 = "qcow2"
    RAW = "raw"


# QEMU orchestrator's per-node configuration options.
@dataclass_json()
@dataclass
class BaseLibvirtNodeSchema:
    # Path to the OS disk image to use for the node.
    disk_img: str = ""
    # Format of the disk image specified above.
    disk_img_format: str = ""
    # Pass to resize the guest image os disk
    disk_img_resize_gib: Optional[int] = None
    # Configuration options for cloud-init.
    cloud_init: Optional[CloudInitSchema] = None

    # Configuration options for ignition.
    ignition: Optional[bool] = False
    # Whether to use UEFI or BIOS firmware.
    # Defaults to UEFI.
    firmware_type: str = ""
    # The machine type to emulate.
    # Defaults to the system's default (typically: i440fx).
    # Typical options available include:
    # - i440fx (legacy, no secure-boot support)
    # - q35
    machine_type: str = ""
    # Whether to enable secure boot.
    enable_secure_boot: bool = False

    # Configuration options for device-passthrough.
    device_passthrough: Optional[List[LibvirtDevicePassthroughSchema]] = None


# QEMU orchestrator's per-node configuration options.
# This ensures backward compatibility with existing runbooks that specify the
# qcow2 property.
@dataclass_json()
@dataclass
class QemuNodeSchema(BaseLibvirtNodeSchema):
    # The disk image to use for the node.
    # The file must use the qcow2 file format and should not be changed during test
    # execution.
    qcow2: str = ""

    def __post_init__(self) -> None:
        if self.ignition and self.cloud_init:
            raise LisaException(
                "Can't use Ignition and cloud-init provisioning at the same time"
            )
        if not self.disk_img:
            self.disk_img = self.qcow2
            self.disk_img_format = DiskImageFormat.QCOW2.value


@dataclass_json()
@dataclass
class KernelSchema:
    path: str = ""
    is_remote_path: bool = False


@dataclass_json()
@dataclass
class CloudHypervisorNodeSchema(BaseLibvirtNodeSchema):
    # Local or remote path to the cloud-hypervisor kernel.
    kernel: Optional[KernelSchema] = None
