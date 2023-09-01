# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import dataclass
from typing import Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.util import InitializableMixin, get_matched_str, subclasses
from lisa.util.logger import get_logger

from .schema import IpGetterSchema


class IpGetterChecker(subclasses.BaseClassWithRunbookMixin, InitializableMixin):
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
    # ipaddr=X.XX.XXX.X
    __ip_addr_regex = re.compile(r"(?P<ip_addr>[\d.]+)", re.M)

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
        matched = get_matched_str(" ".join(lines), self.__ip_addr_regex, True)
        assert matched is not None, (
            f"Could not get ip from content of file {self.file_single_runbook.file}"
            f" {' '.join(lines)}"
        )
        return matched
