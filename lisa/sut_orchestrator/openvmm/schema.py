# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from typing import List, Optional

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.secret import PATTERN_HEADTAIL, add_secret
from lisa.util import LisaException

from .. import OPENVMM

OPENVMM_BOOT_MODE_UEFI = "uefi"
OPENVMM_NETWORK_MODE_USER = "user"
OPENVMM_SERIAL_MODE_STDERR = "stderr"
OPENVMM_SERIAL_MODE_FILE = "file"


@dataclass_json()
@dataclass
class OpenVmmInstallerSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    force_install: bool = False


@dataclass_json()
@dataclass
class OpenVmmSourceInstallerSchema(OpenVmmInstallerSchema):
    repo: str = "https://github.com/microsoft/openvmm.git"
    ref: str = ""
    auth_token: str = ""
    install_path: str = "/usr/local/bin/openvmm"
    features: List[str] = field(default_factory=list)


@dataclass_json()
@dataclass
class OpenVmmUefiSchema:
    firmware_path: str = ""
    firmware_is_remote_path: bool = False


@dataclass_json()
@dataclass
class OpenVmmSerialSchema:
    mode: str = OPENVMM_SERIAL_MODE_FILE

    def __post_init__(self) -> None:
        if self.mode not in [
            OPENVMM_SERIAL_MODE_STDERR,
            OPENVMM_SERIAL_MODE_FILE,
        ]:
            raise LisaException(
                f"serial mode '{self.mode}' is not supported. "
                f"Supported values: {OPENVMM_SERIAL_MODE_STDERR}, "
                f"{OPENVMM_SERIAL_MODE_FILE}"
            )


@dataclass_json()
@dataclass
class OpenVmmNetworkSchema:
    mode: str = OPENVMM_NETWORK_MODE_USER
    connection_address: str = ""
    consomme_cidr: str = ""
    ssh_port: int = 22

    def __post_init__(self) -> None:
        if self.mode != OPENVMM_NETWORK_MODE_USER:
            raise LisaException(
                f"network mode '{self.mode}' is not supported. "
                f"Supported values: {OPENVMM_NETWORK_MODE_USER}"
            )
        if not self.connection_address:
            raise LisaException(
                "connection_address is required for OpenVMM guest networking"
            )


@dataclass_json()
@dataclass
class OpenVmmGuestNodeSchema(schema.GuestNode):
    type: str = OPENVMM
    username: str = "root"
    password: str = ""
    private_key_file: str = ""
    lisa_working_dir: str = "/var/tmp"
    boot_mode: str = OPENVMM_BOOT_MODE_UEFI
    uefi: Optional[OpenVmmUefiSchema] = None
    disk_img: str = ""
    disk_img_is_remote_path: bool = False
    openvmm_binary: str = "/usr/local/bin/openvmm"
    serial: OpenVmmSerialSchema = field(default_factory=OpenVmmSerialSchema)
    network: OpenVmmNetworkSchema = field(default_factory=OpenVmmNetworkSchema)
    extra_args: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        add_secret(self.username, PATTERN_HEADTAIL)
        add_secret(self.password)
        add_secret(self.private_key_file)
        if self.boot_mode != OPENVMM_BOOT_MODE_UEFI:
            raise LisaException(
                f"boot mode '{self.boot_mode}' is not supported. "
                f"Supported values: {OPENVMM_BOOT_MODE_UEFI}"
            )
        if not self.uefi or not self.uefi.firmware_path:
            raise LisaException(
                "uefi.firmware_path is required for UEFI OpenVMM guests"
            )
        if not self.disk_img:
            raise LisaException("disk_img is required for UEFI OpenVMM guests")
