# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import dataclass, field
from typing import Type

import requests
from dataclasses_json import dataclass_json

from lisa import schema
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
