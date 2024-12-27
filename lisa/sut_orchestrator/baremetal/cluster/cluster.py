# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Type

from lisa import features, schema
from lisa.environment import Environment
from lisa.util import InitializableMixin, subclasses
from lisa.util.logger import Logger, get_logger

from ..schema import ClientCapability, ClientSchema, ClusterSchema


class Cluster(subclasses.BaseClassWithRunbookMixin, InitializableMixin):
    def __init__(
        self,
        runbook: ClusterSchema,
        parent_logger: Logger,
    ) -> None:
        super().__init__(runbook=runbook)
        self.cluster_runbook: ClusterSchema = self.runbook
        self._log = get_logger(name=self.__class__.__name__, parent=parent_logger)

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

    def get_client_capability(self, client: ClientSchema) -> ClientCapability:
        # If the cluster doesn't support detecting capability, return an empty
        # capability.
        if client.capability:
            return client.capability
        cluster_capabilities = ClientCapability()
        # Give minimun values to pass basic checks.
        cluster_capabilities.core_count = 1
        cluster_capabilities.free_memory_mb = 512
        return cluster_capabilities

    def cleanup(self) -> None:
        pass
