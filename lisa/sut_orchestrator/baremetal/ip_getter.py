# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import time
from dataclasses import dataclass, field
from typing import Type

import requests
from dataclasses_json import dataclass_json

from lisa import schema
from lisa.features import SerialConsole
from lisa.node import Node
from lisa.util import (
    InitializableMixin,
    LisaException,
    field_metadata,
    get_matched_str,
    subclasses,
)
from lisa.util.logger import get_logger

from .schema import IpGetterSchema


class IpGetterChecker(subclasses.BaseClassWithRunbookMixin, InitializableMixin):
    ip_addr_regex = re.compile(r"(?P<ip_addr>[\d.]+)", re.M)

    def __init__(
        self,
        runbook: IpGetterSchema,
    ) -> None:
        super().__init__(runbook=runbook)
        self.ip_getter_runbook: IpGetterSchema = self.runbook
        self._log = get_logger("ip_getter", self.__class__.__name__)

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return IpGetterSchema

    def get_ip(self) -> str:
        raise NotImplementedError()

    def get_ip_from_node(self, node: Node) -> str:
        return self.get_ip()


@dataclass_json()
@dataclass
class FileSingleSchema(IpGetterSchema):
    file: str = ""


class FileSingleChecker(IpGetterChecker):
    def __init__(
        self,
        runbook: FileSingleSchema,
    ) -> None:
        super().__init__(runbook=runbook)
        self.file_single_runbook: FileSingleSchema = self.runbook
        self._log = get_logger("file_single", self.__class__.__name__)

    @classmethod
    def type_name(cls) -> str:
        return "file_single"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return FileSingleSchema

    def get_ip(self) -> str:
        with open(self.file_single_runbook.file) as f:
            lines = f.readlines()
        matched = get_matched_str(" ".join(lines), self.ip_addr_regex, True)
        assert matched is not None, (
            f"Could not get ip from content of file {self.file_single_runbook.file}"
            f" {' '.join(lines)}"
        )
        return matched


@dataclass_json()
@dataclass
class HttpSchema(IpGetterSchema):
    url: str = field(default="", metadata=field_metadata(required=True))


class HttpChecker(IpGetterChecker):
    def __init__(
        self,
        runbook: HttpSchema,
    ) -> None:
        super().__init__(runbook=runbook)
        self.http_runbook: HttpSchema = self.runbook
        self._log = get_logger("http", self.__class__.__name__)

    @classmethod
    def type_name(cls) -> str:
        return "http"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return HttpSchema

    def get_ip(self) -> str:
        url = self.http_runbook.url
        response = requests.get(url, timeout=20)
        if response.status_code == 200:
            matched = get_matched_str(response.text, self.ip_addr_regex, True)
            assert (
                matched is not None
            ), f"Could not get ip from content from {url}: content is {response.text}"
            return matched
        raise LisaException(
            f"Failed to fetch content. Status code: {response.status_code}"
        )


@dataclass_json()
@dataclass
class SerialSchema(IpGetterSchema):
    type: str = "serial"
    command: str = (
        "DEV=$(ip -4 -o route show default | "
        "sed -n 's/.* dev \\([^ ]*\\).*/\\1/p' | sed -n '1p'); "
        'if [ -n "$DEV" ]; then '
        'ip -4 -o addr show dev "$DEV" scope global | '
        "sed -n 's/.* inet \\([0-9.]*\\)\\/.*/\\1/p' | sed -n '1p'; "
        "else ip -4 -o addr show scope global | "
        "sed -n 's/.* inet \\([0-9.]*\\)\\/.*/\\1/p' | sed -n '1p'; fi"
    )
    timeout: int = 600


class SerialChecker(IpGetterChecker):
    _start_marker = "__LISA_IP_START__"
    _end_marker = "__LISA_IP_END__"
    ip_addr_regex = re.compile(
        r"(?<![\d.])(?P<ip_addr>(?!127\.)(?:\d{1,3}\.){3}\d{1,3})(?![\d.])",
        re.M,
    )

    def __init__(self, runbook: SerialSchema) -> None:
        super().__init__(runbook=runbook)
        self.serial_runbook: SerialSchema = self.runbook
        self._log = get_logger("serial", self.__class__.__name__)

    @classmethod
    def type_name(cls) -> str:
        return "serial"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return SerialSchema

    def get_ip(self) -> str:
        raise LisaException("serial ip getter requires a node")

    def get_ip_from_node(self, node: Node) -> str:
        serial_console = node.features[SerialConsole]
        previous_output = serial_console.get_console_log(force_run=True)
        deadline = time.time() + self.serial_runbook.timeout
        while time.time() < deadline:
            serial_console.write(
                f"echo {self._start_marker}; {self.serial_runbook.command}; "
                f"echo {self._end_marker}"
            )
            output = serial_console.get_console_log(force_run=True)
            fresh_output = (
                output[len(previous_output) :]
                if output.startswith(previous_output)
                else output
            )
            marker_start = fresh_output.rfind(self._start_marker)
            marker_end = fresh_output.find(self._end_marker, marker_start + 1)
            if marker_start >= 0 and marker_end > marker_start:
                command_output = fresh_output[
                    marker_start + len(self._start_marker) : marker_end
                ]
                matched = get_matched_str(command_output, self.ip_addr_regex, True)
                if matched:
                    return matched
            time.sleep(1)
        raise LisaException(
            "Could not get a non-loopback IPv4 address from serial console output"
        )
