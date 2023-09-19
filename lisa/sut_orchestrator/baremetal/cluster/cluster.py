# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Type

from lisa import features, schema
from lisa.environment import Environment
from lisa.util import InitializableMixin, subclasses
from lisa.util.logger import get_logger

from ..schema import ClientCapabilities, ClientSchema, ClusterSchema


class Cluster(subclasses.BaseClassWithRunbookMixin, InitializableMixin):
    def __init__(
        self,
        runbook: ClusterSchema,
    ) -> None:
        super().__init__(runbook=runbook)
        self.cluster_runbook: ClusterSchema = self.runbook
        self._log = get_logger("cluster", self.__class__.__name__)

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return ClusterSchema

    def deploy(self, environment: Environment) -> Any:
        raise NotImplementedError()

    def has_serial_console(self) -> bool:
        raise NotImplementedError()

    def get_serial_console(self) -> Type[features.SerialConsole]:
        raise NotImplementedError()

    def get_start_stop(self) -> Type[features.StartStop]:
        raise NotImplementedError()

    def get_client_capabilities(self, client: ClientSchema) -> ClientCapabilities:
        raise NotImplementedError()

    def cleanup(self) -> None:
        raise NotImplementedError()
