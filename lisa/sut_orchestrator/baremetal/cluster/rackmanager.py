# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any, Type

from lisa import features, schema
from lisa.environment import Environment
from lisa.node import quick_connect

from ..platform_ import BareMetalPlatform
from ..schema import RackManagerSchema
from .cluster import Cluster


class RackManagerStartStop(features.StartStop):
    def init_rack_manager(self) -> None:
        platform: BareMetalPlatform = self._platform  # type: ignore
        self.cluster: RackManager = platform.cluster  # type: ignore

    def _stop(
        self, wait: bool = True, state: features.StopState = features.StopState.Shutdown
    ) -> None:
        if state == features.StopState.Hibernate:
            raise NotImplementedError(
                "baremetal orchestrator does not support hibernate stop"
            )
        self.init_rack_manager()
        self.cluster.reset("off")

    def _start(self, wait: bool = True) -> None:
        self.init_rack_manager()
        self.cluster.reset("on")

    def _restart(self, wait: bool = True) -> None:
        self.init_rack_manager()
        self.cluster.reset("reset")


class RackManager(Cluster):
    def __init__(self, runbook: RackManagerSchema, **kwargs: Any) -> None:
        super().__init__(runbook, **kwargs)
        self.rm_runbook: RackManagerSchema = self.runbook

    @classmethod
    def type_name(cls) -> str:
        return "rackmanager"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return RackManagerSchema

    def get_start_stop(self) -> Type[features.StartStop]:
        return RackManagerStartStop

    def connect_to_rack_manager(self) -> None:
        assert self.rm_runbook.connection, "connection is required for rackmanager"
        self.rm_runbook.connection.name = "rackmanager"
        self.rm_node = quick_connect(
            self.rm_runbook.connection, logger_name="rackmanager"
        )

    def deploy(self, environment: Environment) -> Any:
        self.reset("off")
        self.reset("on")

    def reset(self, operation: str) -> None:
        self.connect_to_rack_manager()
        assert self.rm_runbook.client, "client is required for rackmanager"
        for client in self.rm_runbook.client:
            assert (
                client.management_port
            ), "management_port is required for rackmanager client"
            self.rm_node.execute(f"set system {operation} -i {client.management_port}")
        self._log.debug(f"client has been {operation} successfully")
