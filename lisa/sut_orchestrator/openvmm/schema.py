# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from typing import List, Optional, Union

from dataclasses_json import config, dataclass_json

from lisa import schema
from lisa.secret import PATTERN_HEADTAIL, add_secret
from lisa.util import LisaException

from .. import OPENVMM

OPENVMM_BOOT_MODE_UEFI = "uefi"
OPENVMM_ADDRESS_MODE_DISCOVER = "discover"
OPENVMM_ADDRESS_MODE_STATIC = "static"
OPENVMM_NETWORK_MODE_NONE = "none"
OPENVMM_NETWORK_MODE_USER = "user"
OPENVMM_NETWORK_MODE_TAP = "tap"
OPENVMM_SERIAL_MODE_STDERR = "stderr"
OPENVMM_SERIAL_MODE_FILE = "file"


@dataclass_json()
@dataclass
class CloudInitSchema:
    extra_user_data: Optional[Union[str, List[str]]] = None


@dataclass_json()
@dataclass
class OpenVmmInstallerSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    force_install: bool = False


@dataclass_json()
@dataclass
class OpenVmmSourceInstallerSchema(OpenVmmInstallerSchema):
    repo: str = "https://github.com/microsoft/openvmm.git"
    ref: str = ""
    auth_token: str = field(
        default="", repr=False, metadata=config(exclude=lambda x: True)
    )
    install_path: str = "/usr/local/bin/openvmm"
    features: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.auth_token:
            add_secret(self.auth_token)


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
    mode: str = OPENVMM_NETWORK_MODE_NONE
    address_mode: str = OPENVMM_ADDRESS_MODE_DISCOVER
    tap_name: str = ""
    bridge_name: str = ""
    tap_host_cidr: str = "10.0.0.1/24"
    guest_address: str = ""
    connection_address: str = ""
    consomme_cidr: str = ""
    ssh_port: int = field(
        default=22,
        metadata=schema.field_metadata(
            field_function=schema.fields.Int,
            validate=schema.validate.Range(min=1, max=65535),
        ),
    )
    forward_ssh_port: bool = False
    forwarded_port: int = field(
        default=0,
        metadata=schema.field_metadata(
            field_function=schema.fields.Int,
            validate=schema.validate.Range(min=0, max=65535),
        ),
    )

    def __post_init__(self) -> None:
        if self.mode not in [
            OPENVMM_NETWORK_MODE_NONE,
            OPENVMM_NETWORK_MODE_USER,
            OPENVMM_NETWORK_MODE_TAP,
        ]:
            raise LisaException(
                f"network mode '{self.mode}' is not supported. "
                f"Supported values: {OPENVMM_NETWORK_MODE_NONE}, "
                f"{OPENVMM_NETWORK_MODE_USER}, "
                f"{OPENVMM_NETWORK_MODE_TAP}"
            )
        if self.mode == OPENVMM_NETWORK_MODE_TAP and not self.tap_name:
            raise LisaException("tap_name is required when network mode is 'tap'")
        if self.mode == OPENVMM_NETWORK_MODE_TAP and not self.tap_host_cidr:
            raise LisaException("tap_host_cidr is required when network mode is 'tap'")
        if self.address_mode not in [
            OPENVMM_ADDRESS_MODE_DISCOVER,
            OPENVMM_ADDRESS_MODE_STATIC,
        ]:
            raise LisaException(
                f"address_mode '{self.address_mode}' is not supported. "
                f"Supported values: {OPENVMM_ADDRESS_MODE_DISCOVER}, "
                f"{OPENVMM_ADDRESS_MODE_STATIC}"
            )

        if self.mode == OPENVMM_NETWORK_MODE_NONE:
            return

        if (
            self.address_mode == OPENVMM_ADDRESS_MODE_DISCOVER
            and self.mode != OPENVMM_NETWORK_MODE_TAP
        ):
            raise LisaException(
                "address_mode 'discover' is supported only with tap networking"
            )

        if self.address_mode == OPENVMM_ADDRESS_MODE_STATIC and not self.guest_address:
            raise LisaException(
                "guest_address is required when address_mode is 'static'"
            )

        if self.forward_ssh_port:
            if self.mode != OPENVMM_NETWORK_MODE_TAP:
                raise LisaException(
                    "forward_ssh_port is supported only with tap networking"
                )
            if (
                self.address_mode == OPENVMM_ADDRESS_MODE_STATIC
                and not self.guest_address
            ):
                raise LisaException(
                    "guest_address is required when forward_ssh_port is enabled"
                )
            if self.forwarded_port <= 0 or self.forwarded_port > 65535:
                raise LisaException(
                    "forwarded_port must be between 1 and 65535 when "
                    "forward_ssh_port is enabled"
                )


@dataclass_json()
@dataclass
class OpenVmmGuestNodeSchema(schema.GuestNode):
    type: str = OPENVMM
    username: str = "root"
    password: str = field(
        default="", repr=False, metadata=config(exclude=lambda x: True)
    )
    private_key_file: str = ""
    cloud_init: Optional[CloudInitSchema] = None
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
        if (
            self.cloud_init
            and not self.private_key_file
            and not self.password
            and not self.cloud_init.extra_user_data
        ):
            raise LisaException(
                "OpenVMM cloud_init requires private_key_file, password, or "
                "cloud_init.extra_user_data to provision guest access"
            )
