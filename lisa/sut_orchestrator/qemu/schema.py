from dataclasses import dataclass
from typing import Optional

from dataclasses_json import dataclass_json


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
    pass


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
