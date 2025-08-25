# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from lisa import feature, schema
from lisa.environment import Environment
from lisa.node import Node
from lisa.platform_ import Platform
from lisa.sut_orchestrator import platform_utils
from lisa.util.logger import Logger
from lisa.util.subclasses import Factory

from .. import BAREMETAL
from .bootconfig import BootConfig
from .build import Build
from .cluster.cluster import Cluster
from .context import get_build_context, get_node_context
from .features import SecurityProfile, SerialConsole, StartStop
from .ip_getter import IpGetterChecker
from .key_loader import KeyLoader
from .readychecker import ReadyChecker
from .schema import BareMetalPlatformSchema, BuildSchema
from .source import Source


def convert_to_baremetal_node_space(node_space: schema.NodeSpace) -> None:
    """
    Convert generic FeatureSettings to baremetal-specific types.
    It converts generic FeatureSettings (like SecurityProfile) to platform-specific
    types that have proper typing and platform-specific behavior.
    """
    if not node_space:
        return

    feature.reload_platform_features(node_space, BareMetalPlatform.supported_features())


class BareMetalPlatform(Platform):
    def __init__(
        self,
        runbook: schema.Platform,
    ) -> None:
        super().__init__(runbook=runbook)

        self._environment_information_hooks = {
            platform_utils.KEY_VMM_VERSION: platform_utils.get_vmm_version,
            platform_utils.KEY_MSHV_VERSION: platform_utils.get_mshv_version,
        }

    @classmethod
    def type_name(cls) -> str:
        return BAREMETAL

    @classmethod
    def supported_features(cls) -> List[Type[feature.Feature]]:
        return [StartStop, SerialConsole, SecurityProfile]

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

        self.cluster = self.cluster_factory.create_by_runbook(
            self._cluster_runbook, parent_logger=self._log
        )
        self.cluster.initialize()

    def _get_node_information(self, node: Node) -> Dict[str, str]:
        information: Dict[str, str] = {}
        for key, method in self._environment_information_hooks.items():
            node.log.debug(f"detecting {key} ...")
            try:
                value = method(node)
                if value:
                    information[key] = value
            except Exception as e:
                node.log.exception(f"error on get {key}.", exc_info=e)
        return information

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        assert self.cluster.runbook.client, "no client is specified in the runbook"

        assert environment.runbook.nodes_requirement, "nodes requirement is required"
        if len(environment.runbook.nodes_requirement) > 1:
            # so far only supports one node
            return False

        # Convert test requirements to platform-specific feature types
        if environment.runbook.nodes_requirement:
            for node_requirement in environment.runbook.nodes_requirement:
                convert_to_baremetal_node_space(node_requirement)

        return self._check_capability(environment, log, self.cluster.client)

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        ready_checker: Optional[ReadyChecker] = None

        # process the cluster elements from runbook
        self._predeploy_environment(environment, log)

        # deploy cluster
        self.cluster.deploy(environment)

        if self._cluster_runbook.ready_checker:
            ready_checker = self.ready_checker_factory.create_by_runbook(
                self._cluster_runbook.ready_checker, parent_logger=log
            )

        for index, node in enumerate(environment.nodes.list()):
            node_context = get_node_context(node)

            # ready checker
            if ready_checker:
                ready_checker.is_ready(node)

            assert node_context.client.connection, "connection is required"
            # get ip address
            if self._cluster_runbook.ip_getter:
                ip_getter = self.ip_getter_factory.create_by_runbook(
                    self._cluster_runbook.ip_getter
                )

                node_context.client.connection.address = ip_getter.get_ip()

            node.name = f"node_{index}"
            node.initialize()

        self._log.debug(f"deploy environment {environment.name} successfully")

    def _delete_environment(self, environment: Environment, log: Logger) -> None:
        self.cluster.delete(environment, log)

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
        key_file = ""
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
                self._cluster_runbook.ready_checker,
                parent_logger=log,
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
        for index, node_space in enumerate(environment.runbook.nodes_requirement):
            assert isinstance(
                node_space, schema.NodeSpace
            ), f"actual: {type(node_space)}"
            node = environment.create_node_from_requirement(node_space)

            node.features = feature.Features(node, self)
            node_context = get_node_context(node)

            if (
                not self.cluster.runbook.client[index].connection.password
                and self.cluster.runbook.client[index].connection.private_key_file == ""
            ):
                assert key_file, "Expected key_file to be set"
                self.cluster.runbook.client[
                    index
                ].connection.private_key_file = key_file

            node_context.client = self.cluster.runbook.client[index]
            node_context.cluster = self.cluster.runbook
            index = index + 1

    def _check_capability(
        self,
        environment: Environment,
        log: Logger,
        client_capability: schema.NodeSpace,
    ) -> bool:
        if not environment.runbook.nodes_requirement:
            return True

        nodes_requirement = []
        for node_space in environment.runbook.nodes_requirement:
            if not node_space.check(client_capability):
                return False

            node_requirement = node_space.generate_min_capability(client_capability)
            nodes_requirement.append(node_requirement)

        environment.runbook.nodes_requirement = nodes_requirement
        return True

    def _cleanup(self) -> None:
        self.cluster.cleanup()
