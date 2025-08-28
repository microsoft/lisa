# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Type

from lisa import features, schema, search_space
from lisa.environment import Environment
from lisa.util import InitializableMixin, subclasses
from lisa.util.logger import Logger, get_logger

from ..features import SecurityProfile
from ..schema import ClientSchema, ClusterSchema


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

    def delete(self, environment: Environment, log: Logger) -> None:
        # the delete is not required for all clusters.
        pass

    def get_serial_console(self) -> Type[features.SerialConsole]:
        raise NotImplementedError()

    def get_start_stop(self) -> Type[features.StartStop]:
        raise NotImplementedError()

    def get_client_capability(self, client: ClientSchema) -> schema.Capability:
        # If the cluster doesn't support detecting capability, return an empty
        # capability.
        if client.capability:
            return client.capability

        capability = schema.Capability()
        # Give minimun values to pass basic checks.
        capability.core_count = 1
        capability.memory_mb = 512
        return capability

    def cleanup(self) -> None:
        pass

    def prepare_clients(self) -> None:
        client_runbook = self.runbook.client[0]
        client_capability = self.get_client_capability(client_runbook)

        # to compatible with previous schema, use the whole client as extended
        # runbook.
        schema_type = self.runbook.type
        extended_schema = client_runbook.to_dict()

        if client_capability.extended_schemas is None:
            client_capability.extended_schemas = {}
        client_capability.extended_schemas[schema_type] = extended_schema
        self._fill_capability(client_capability)

        self.client = client_capability

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self.prepare_clients()

    def _fill_capability(self, node_capability: schema.NodeSpace) -> None:
        node_capability.node_count = 1
        node_capability.disk = schema.DiskOptionSettings(
            data_disk_count=search_space.IntRange(min=0),
            data_disk_size=search_space.IntRange(min=1),
        )
        node_capability.network_interface = schema.NetworkInterfaceOptionSettings()
        node_capability.network_interface.max_nic_count = 1
        node_capability.network_interface.nic_count = 1
        node_capability.network_interface.data_path = search_space.SetSpace[
            schema.NetworkDataPath
        ](
            is_allow_set=True,
            items=[schema.NetworkDataPath.Sriov, schema.NetworkDataPath.Synthetic],
        )
        node_capability.gpu_count = 0
        node_capability.features = search_space.SetSpace[schema.FeatureSettings](
            is_allow_set=True,
            items=[
                schema.FeatureSettings.create(features.SerialConsole.name()),
                schema.FeatureSettings.create(features.StartStop.name()),
                SecurityProfile.create_setting(),
            ],
        )
