# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import ipaddress
import re
import shlex
from dataclasses import dataclass, field
from typing import List, Optional

from dataclasses_json import config, dataclass_json

from lisa import schema
from lisa.secret import PATTERN_HEADTAIL, add_secret
from lisa.sut_orchestrator.util.schema import CloudInitSchema
from lisa.util import LisaException

from .. import OPENVMM

OPENVMM_BOOT_MODE_UEFI = "uefi"
OPENVMM_ADDRESS_MODE_DISCOVER = "discover"
OPENVMM_ADDRESS_MODE_STATIC = "static"
OPENVMM_NETWORK_MODE_USER = "user"
OPENVMM_NETWORK_MODE_TAP = "tap"
OPENVMM_CONNECTION_MODE_FORWARDED_PORT = "forwarded_port"
OPENVMM_CONNECTION_MODE_HOST_PROXY = "host_proxy"
OPENVMM_SERIAL_MODE_STDERR = "stderr"
OPENVMM_SERIAL_MODE_FILE = "file"
# Keep raw disk growth opt-in so existing OpenVMM runbooks don't mutate
# user-supplied images unless they explicitly request it.
OPENVMM_DEFAULT_MIN_RAW_DISK_SIZE_GB = 0
OPENVMM_MAX_INTERFACE_NAME_LENGTH = 15
OPENVMM_INTERFACE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


def _decode_extra_args(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    raise LisaException(
        "OpenVMM extra_args must be a string or list of strings, "
        f"not '{type(value).__name__}'"
    )


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
    mode: str = OPENVMM_NETWORK_MODE_USER
    connection_mode: str = OPENVMM_CONNECTION_MODE_FORWARDED_PORT
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

    def _validate_tap_host_cidr(self) -> None:
        if self.mode != OPENVMM_NETWORK_MODE_TAP:
            return

        if not self.tap_host_cidr:
            raise LisaException("tap_host_cidr is required when network mode is 'tap'")

        try:
            ipaddress.ip_interface(self.tap_host_cidr)
        except ValueError as identifier:
            raise LisaException(
                "tap_host_cidr "
                f"'{self.tap_host_cidr}' is invalid for OpenVMM tap networking. "
                "Use an interface CIDR like '10.0.0.1/24'."
            ) from identifier

    def _validate_interface_name(self, field_name: str, value: str) -> None:
        if len(value) > OPENVMM_MAX_INTERFACE_NAME_LENGTH:
            raise LisaException(
                f"{field_name} '{value}' is invalid for OpenVMM tap networking. "
                f"Use 1-{OPENVMM_MAX_INTERFACE_NAME_LENGTH} characters."
            )
        if not OPENVMM_INTERFACE_NAME_PATTERN.fullmatch(value):
            raise LisaException(
                f"{field_name} '{value}' is invalid for OpenVMM tap networking. "
                "Use only letters, digits, '_', '-', or '.'."
            )

    def validate_tap_interface_names(self) -> None:
        if self.mode != OPENVMM_NETWORK_MODE_TAP:
            return
        if not self.tap_name:
            raise LisaException("tap_name is required when network mode is 'tap'")
        self._validate_interface_name("tap_name", self.tap_name)
        if self.bridge_name:
            self._validate_interface_name("bridge_name", self.bridge_name)

    def __post_init__(self) -> None:
        if self.connection_mode not in [
            OPENVMM_CONNECTION_MODE_FORWARDED_PORT,
            OPENVMM_CONNECTION_MODE_HOST_PROXY,
        ]:
            raise LisaException(
                f"connection_mode '{self.connection_mode}' is not supported. "
                f"Supported values: {OPENVMM_CONNECTION_MODE_FORWARDED_PORT}, "
                f"{OPENVMM_CONNECTION_MODE_HOST_PROXY}"
            )
        if self.mode not in [
            OPENVMM_NETWORK_MODE_USER,
            OPENVMM_NETWORK_MODE_TAP,
        ]:
            raise LisaException(
                f"network mode '{self.mode}' is not supported for OpenVMM guests. "
                f"Supported values: {OPENVMM_NETWORK_MODE_USER}, "
                f"{OPENVMM_NETWORK_MODE_TAP}"
            )
        if self.mode == OPENVMM_NETWORK_MODE_TAP:
            self.validate_tap_interface_names()
            self._validate_tap_host_cidr()
        if self.address_mode not in [
            OPENVMM_ADDRESS_MODE_DISCOVER,
            OPENVMM_ADDRESS_MODE_STATIC,
        ]:
            raise LisaException(
                f"address_mode '{self.address_mode}' is not supported. "
                f"Supported values: {OPENVMM_ADDRESS_MODE_DISCOVER}, "
                f"{OPENVMM_ADDRESS_MODE_STATIC}"
            )

        if self.connection_mode == OPENVMM_CONNECTION_MODE_HOST_PROXY:
            if self.mode != OPENVMM_NETWORK_MODE_TAP:
                raise LisaException(
                    "host_proxy connection_mode is supported only with tap networking"
                )
            self.forward_ssh_port = False
            self.forwarded_port = 0
        elif self.forwarded_port:
            self.forward_ssh_port = True

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

        if self.mode == OPENVMM_NETWORK_MODE_USER:
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
    min_raw_disk_size_gb: int = field(
        default=OPENVMM_DEFAULT_MIN_RAW_DISK_SIZE_GB,
        metadata=schema.field_metadata(
            field_function=schema.fields.Int,
            validate=schema.validate.Range(min=0),
        ),
    )
    openvmm_binary: str = "/usr/local/bin/openvmm"
    serial: OpenVmmSerialSchema = field(default_factory=OpenVmmSerialSchema)
    network: OpenVmmNetworkSchema = field(default_factory=OpenVmmNetworkSchema)
    extra_args: List[str] = field(
        default_factory=list,
        metadata=schema.field_metadata(decoder=_decode_extra_args),
    )

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
