# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Type

import requests

from lisa import schema
from lisa.util import ContextMixin, InitializableMixin, subclasses
from lisa.util.logger import get_logger

from .schema import IPPowerSchema


class IPPower(subclasses.BaseClassWithRunbookMixin, ContextMixin, InitializableMixin):
    def __init__(self, runbook: IPPowerSchema) -> None:
        super().__init__(runbook=runbook)
        self._log = get_logger("cluster", self.__class__.__name__)

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return IPPowerSchema

    def on(self, port: int) -> None:
        raise NotImplementedError()

    def off(self, port: int) -> None:
        raise NotImplementedError()


class Ip9285(IPPower):
    def __init__(self, runbook: IPPowerSchema) -> None:
        super().__init__(runbook)
        self._request_cmd = (
            f"http://{runbook.hostname}/set.cmd?"
            f"user={runbook.username}+pass="
            f"{runbook.password}+cmd=setpower+P6"
        )

    @classmethod
    def type_name(cls) -> str:
        return "Ip9285"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return IPPowerSchema

    def on(self, port: int) -> None:
        request_on = f"{self._request_cmd}{port}=1"
        requests.get(request_on)

    def off(self, port: int) -> None:
        request_off = f"{self._request_cmd}{port}=0"
        requests.get(request_off)
