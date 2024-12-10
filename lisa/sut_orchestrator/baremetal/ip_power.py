# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Type

import requests

from lisa import schema
from lisa.util import ContextMixin, InitializableMixin, LisaException, subclasses
from lisa.util.logger import get_logger

from .schema import IPPowerSchema

REQUEST_TIMEOUT = 3
REQUEST_SUCCESS_CODE = 200


class IPPower(subclasses.BaseClassWithRunbookMixin, ContextMixin, InitializableMixin):
    def __init__(self, runbook: IPPowerSchema) -> None:
        super().__init__(runbook=runbook)
        self._log = get_logger("cluster", self.__class__.__name__)

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return IPPowerSchema

    def on(self, port: str) -> None:
        raise NotImplementedError()

    def off(self, port: str) -> None:
        raise NotImplementedError()


class Ip9285(IPPower):
    def __init__(self, runbook: IPPowerSchema) -> None:
        super().__init__(runbook)
        self._request_cmd = (
            f"http://{runbook.host}/set.cmd?"
            f"user={runbook.username}+pass="
            f"{runbook.password}+cmd=setpower+P6"
        )

    @classmethod
    def type_name(cls) -> str:
        return "Ip9285"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return IPPowerSchema

    def on(self, port: str) -> None:
        request_on = f"{self._request_cmd}{port}=1"
        self._set_ip_power(request_on)

    def off(self, port: str) -> None:
        request_off = f"{self._request_cmd}{port}=0"
        self._set_ip_power(request_off)

    def _set_ip_power(self, power_cmd: str) -> None:
        try:
            response = requests.get(power_cmd, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.HTTPError as http_err:
            raise LisaException(f"HTTP error: {http_err} in set_ip_power occurred")
        except Exception as err:
            raise LisaException(f"Other Error: {err} in set_ip_power occurred")
        else:
            self._log.debug(f"Command {power_cmd} in set_ip_power done")
