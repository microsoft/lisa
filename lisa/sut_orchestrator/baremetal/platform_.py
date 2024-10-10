# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from typing import Any, List, Optional, Type

from lisa import RemoteNode, feature, schema, search_space
from lisa.environment import Environment
from lisa.platform_ import Platform
from lisa.util.logger import Logger
from lisa.util.shell import try_connect
from lisa.util.subclasses import Factory

from .. import BAREMETAL
from .bootconfig import BootConfig
from .build import Build
from .cluster.cluster import Cluster
from .context import get_build_context, get_node_context
from .features import SerialConsole, StartStop
from .ip_getter import IpGetterChecker
from .key_loader import KeyLoader
from .readychecker import ReadyChecker
from .schema import BareMetalPlatformSchema, BuildSchema, ClientCapabilities
from .source import Source


class BareMetalPlatform(Platform):
    def __init__(
        self,
        runbook: schema.Platform,
    ) -> None:
        super().__init__(runbook=runbook)

    @classmethod
    def type_name(cls) -> str:
        return BAREMETAL

    @classmethod
    def supported_features(cls) -> List[Type[feature.Feature]]:
        return [StartStop, SerialConsole]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        baremetal_runbook: BareMetalPlatformSchema = self.runbook.get_extended_runbook(
            BareMetalPlatformSchema
        )
        assert baremetal_runbook, "platform runbook cannot be empty"
        self._baremetal_runbook = baremetal_runbook
        self.local_artifacts_path: Optional[List[Path]] = None
        self.ready_checker_factory = Factory[ReadyChecker](ReadyChecker)
        self.cluster_factory = Factory[Cluster](Cluster)
        self.ip_getter_factory = Factory[IpGetterChecker](IpGetterChecker)
        self.key_loader_factory = Factory[KeyLoader](KeyLoader)
        self.source_factory = Factory[Source](Source)
        self.build_factory = Factory[Build](Build)
        self.boot_config_factory = Factory[BootConfig](BootConfig)
        # currently only support one cluster
        assert self._baremetal_runbook.cluster, "no cluster is specified in the runbook"
        self._cluster_runbook = self._baremetal_runbook.cluster[0]
        self.cluster = self.cluster_factory.create_by_runbook(self._cluster_runbook)

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        assert self.cluster.runbook.client, "no client is specified in the runbook"

        client_capabilities = self.cluster.get_client_capabilities(
            self.cluster.runbook.client[0]
        )
        return self._configure_node_capabilities(environment, log, client_capabilities)

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        # process the cluster elements from runbook
        self._predeploy_environment(environment, log)

        # deploy cluster
        self.cluster.deploy(environment)

        if self._cluster_runbook.ready_checker:
            ready_checker = self.ready_checker_factory.create_by_runbook(
                self._cluster_runbook.ready_checker
            )

        for index, node in enumerate(environment.nodes.list()):
            node_context = get_node_context(node)

            # ready checker
            if ready_checker:
                ready_checker.is_ready(node)

            # get ip address
            if self._cluster_runbook.ip_getter:
                ip_getter = self.ip_getter_factory.create_by_runbook(
                    self._cluster_runbook.ip_getter
                )
                node_context.connection.address = ip_getter.get_ip()

            assert isinstance(node, RemoteNode), f"actual: {type(node)}"
            node.name = f"node_{index}"
            try_connect(node_context.connection)

        self._log.debug(f"deploy environment {environment.name} successfully")

    def _copy(self, build_schema: BuildSchema, sources_path: List[Path]) -> None:
        if sources_path:
            build = self.build_factory.create_by_runbook(build_schema)
            build.copy(
                sources_path=sources_path,
                files_map=build_schema.files,
            )
        else:
            self._log.debug("no copied source path specified, skip copy")

    def _predeploy_environment(self, environment: Environment, log: Logger) -> None:
        # download source (shared, check if it's copied)
        if self._baremetal_runbook.source:
            if not self.local_artifacts_path:
                source = self.source_factory.create_by_runbook(
                    self._baremetal_runbook.source
                )
                self._log.debug(f"source build '{source.type_name()}'")
                self.local_artifacts_path = source.download()
            else:
                self._log.debug(
                    "build source has been downloaded in "
                    f"'{self.local_artifacts_path}',"
                    " skip download again"
                )
        else:
            self._log.debug("no build source is specified in the runbook")

        ready_checker: Optional[ReadyChecker] = None
        # ready checker cleanup
        if self._cluster_runbook.ready_checker:
            ready_checker = self.ready_checker_factory.create_by_runbook(
                self._cluster_runbook.ready_checker
            )
            ready_checker.clean_up()

        # copy build if source exists
        if self.cluster.runbook.build:
            build = self.build_factory.create_by_runbook(self.cluster.runbook.build)
            build_context = get_build_context(build)
            if build_context.is_copied:
                self._log.debug("build is already copied, skip copy")
            else:
                assert self.local_artifacts_path, "no build source is specified"
                self._copy(
                    self.cluster.runbook.build, sources_path=self.local_artifacts_path
                )
                build_context.is_copied = True

        if self.cluster.runbook.boot_config:
            boot_config = self.boot_config_factory.create_by_runbook(
                self.cluster.runbook.boot_config
            )
            boot_config.config()

        if self.cluster.runbook.key_loader:
            key_loader = self.key_loader_factory.create_by_runbook(
                self.cluster.runbook.key_loader
            )
            if self.local_artifacts_path:
                key_file = key_loader.load_key(self.local_artifacts_path)

        assert environment.runbook.nodes_requirement, "no node is specified"
        for node_space in environment.runbook.nodes_requirement:
            assert isinstance(
                node_space, schema.NodeSpace
            ), f"actual: {type(node_space)}"
            environment.create_node_from_requirement(node_space)

        for index, node in enumerate(environment.nodes.list()):
            node_context = get_node_context(node)

            if (
                not self.cluster.runbook.client[index].connection.password
                and self.cluster.runbook.client[index].connection.private_key_file == ""
            ):
                self.cluster.runbook.client[
                    index
                ].connection.private_key_file = key_file

            connection_info = schema.ConnectionInfo(
                address=self.cluster.runbook.client[index].connection.address,
                port=self.cluster.runbook.client[index].connection.port,
                username=self.cluster.runbook.client[index].connection.username,
                private_key_file=self.cluster.runbook.client[
                    index
                ].connection.private_key_file,
                password=self.cluster.runbook.client[index].connection.password,
            )

            node_context.connection = connection_info
            index = index + 1

    def _configure_node_capabilities(
        self,
        environment: Environment,
        log: Logger,
        cluster_capabilities: ClientCapabilities,
    ) -> bool:
        if not environment.runbook.nodes_requirement:
            return True

        nodes_capabilities = self._create_node_capabilities(cluster_capabilities)

        nodes_requirement = []
        for node_space in environment.runbook.nodes_requirement:
            if not node_space.check(nodes_capabilities):
                return False

            node_requirement = node_space.generate_min_capability(nodes_capabilities)
            nodes_requirement.append(node_requirement)

        environment.runbook.nodes_requirement = nodes_requirement
        return True

    def _create_node_capabilities(
        self, cluster_capabilities: ClientCapabilities
    ) -> schema.NodeSpace:
        node_capabilities = schema.NodeSpace()
        node_capabilities.name = "baremetal"
        node_capabilities.node_count = 1
        node_capabilities.core_count = search_space.IntRange(
            min=1, max=cluster_capabilities.core_count
        )
        node_capabilities.memory_mb = cluster_capabilities.free_memory_mb
        node_capabilities.disk = schema.DiskOptionSettings(
            data_disk_count=search_space.IntRange(min=0),
            data_disk_size=search_space.IntRange(min=1),
        )
        node_capabilities.network_interface = schema.NetworkInterfaceOptionSettings()
        node_capabilities.network_interface.max_nic_count = 1
        node_capabilities.network_interface.nic_count = 1
        node_capabilities.network_interface.data_path = search_space.SetSpace[
            schema.NetworkDataPath
        ](
            is_allow_set=True,
            items=[schema.NetworkDataPath.Sriov, schema.NetworkDataPath.Synthetic],
        )
        node_capabilities.gpu_count = 0
        node_capabilities.features = search_space.SetSpace[schema.FeatureSettings](
            is_allow_set=True,
            items=[
                schema.FeatureSettings.create(SerialConsole.name()),
                schema.FeatureSettings.create(StartStop.name()),
            ],
        )

        return node_capabilities

    def _cleanup(self) -> None:
        self.cluster.cleanup()
