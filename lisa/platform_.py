# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import partial
from typing import Any, Dict, List, Type, cast

from lisa import schema
from lisa.environment import Environment, EnvironmentStatus
from lisa.feature import Feature, Features
from lisa.messages import MessageBase
from lisa.node import Node, RemoteNode
from lisa.parameter_parser.runbook import RunbookBuilder
from lisa.util import (
    InitializableMixin,
    LisaException,
    NotMeetRequirementException,
    SkippedException,
    constants,
    hookimpl,
    plugin_manager,
    subclasses,
)
from lisa.util.logger import Logger, get_logger
from lisa.util.perf_timer import create_timer

_get_init_logger = partial(get_logger, "init", "platform")

PlatformStatus = Enum(
    "TestRunStatus",
    [
        "INITIALIZED",
    ],
)


@dataclass
class PlatformMessage(MessageBase):
    type: str = "Platform"
    name: str = ""
    status: PlatformStatus = PlatformStatus.INITIALIZED


class Platform(subclasses.BaseClassWithRunbookMixin, InitializableMixin):
    def __init__(self, runbook: schema.Platform) -> None:
        super().__init__(runbook)
        self._log = get_logger("", self.type_name())
        plugin_manager.register(self)

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return schema.Platform

    @classmethod
    def supported_features(cls) -> List[Type[Feature]]:
        """
        Indicates which feature classes should be used to instance a feature.

        For example, StartStop needs platform implementation, and LISA doesn't
        know which type uses to start/stop for Azure. So Azure platform needs to
        return a type like azure.StartStop. The azure.StartStop use same feature
        string as lisa.features.StartStop. When test cases reference a feature
        by string, it can be instanced to azure.StartStop.
        """
        raise NotImplementedError()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        """
        platform specified initialization
        """
        pass

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        """
        Steps to prepare an environment.

        1. check if platform can meet requirement of this environment.

        2. if #1 is yes, specified platform context, so that the environment can
           be created in deploy phase with same spec as prepared.

        3. set cost for environment priority.

        return True, if environment can be deployed. False, if cannot.
        """
        raise NotImplementedError()

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        raise NotImplementedError()

    def _delete_environment(self, environment: Environment, log: Logger) -> None:
        raise NotImplementedError()

    def _get_environment_information(self, environment: Environment) -> Dict[str, str]:
        return {}

    def _get_node_information(self, node: Node) -> Dict[str, str]:
        return {}

    def _cleanup(self) -> None:
        """
        Called when the platform is being discarded.
        Perform any platform level cleanup work here.
        """
        pass

    @hookimpl
    def get_environment_information(self, environment: Environment) -> Dict[str, str]:
        assert environment.platform
        if environment.platform != self:
            # when multiple platforms are created by multiple runners, it should
            #  call for right platform only.
            return {}

        information: Dict[str, str] = {}
        information["platform"] = environment.platform.type_name()
        try:
            information.update(
                self._get_environment_information(environment=environment)
            )
        except Exception as e:
            self._log.exception(
                "failed to get environment information on platform", exc_info=e
            )

        return information

    @hookimpl
    def get_node_information(self, node: Node) -> Dict[str, str]:
        information: Dict[str, str] = {}
        try:
            information.update(self._get_node_information(node=node))
        except Exception as e:
            self._log.exception(
                "failed to get node information on platform", exc_info=e
            )

        return information

    def prepare_environment(self, environment: Environment) -> Environment:
        """
        return prioritized environments.
            user defined environment is higher priority than test cases,
            and then lower cost is prior to higher.
        """
        log = get_logger(f"prepare[{environment.name}]", parent=self._log)

        # check and fill connection information for RemoteNode. So that the
        # RemoteNodes can share the same connection information with created
        # nodes.
        platform_runbook = cast(schema.Platform, self.runbook)
        for node in environment.nodes.list():
            if isinstance(node, RemoteNode):
                node.set_connection_info_by_runbook(
                    default_username=platform_runbook.admin_username,
                    default_password=platform_runbook.admin_password,
                    default_private_key_file=platform_runbook.admin_private_key_file,
                )

        try:
            is_success = self._prepare_environment(environment, log)
        except NotMeetRequirementException as e:
            raise SkippedException(e)

        if is_success:
            environment.status = EnvironmentStatus.Prepared
        else:
            raise LisaException(
                f"no capability found for environment: {environment.runbook}"
            )

        return environment

    def deploy_environment(self, environment: Environment) -> None:
        platform_runbook = cast(schema.Platform, self.runbook)

        log = get_logger("deploy", parent=environment.log)
        log.info(f"deploying environment: {environment.name}")
        timer = create_timer()
        environment.platform = self
        try:
            self._deploy_environment(environment, log)
        except Exception as identifier:
            environment.status = EnvironmentStatus.Bad
            raise identifier
        environment.status = EnvironmentStatus.Deployed

        # initialize features
        # features may need platform, so create it in platform
        for node in environment.nodes.list():
            # Baremetal platform needs to initialize SerialConsole feature to
            # get serial log from beginning, so the features are created
            # already. If recreate the SerialConsole, the service resource
            # leaks, and SerialConsole cannot be opend again.
            if not hasattr(node, "features"):
                node.features = Features(node, self)
            node.capture_azure_information = platform_runbook.capture_azure_information
            node.capture_boot_time = platform_runbook.capture_boot_time
            node.assert_kernel_error_after_test = (
                platform_runbook.assert_kernel_error_after_test
            )
            node.capture_kernel_config = (
                platform_runbook.capture_kernel_config_information
            )

            if platform_runbook.guest_enabled:
                self._initialize_guest_nodes(node)

        log.info(f"deployed in {timer}")

    def delete_environment(self, environment: Environment) -> None:
        log = get_logger(f"del[{environment.name}]", parent=self._log)

        environment.cleanup()
        if (self.runbook.keep_environment == constants.ENVIRONMENT_KEEP_ALWAYS) or (
            self.runbook.keep_environment == constants.ENVIRONMENT_KEEP_FAILED
            and environment.status == EnvironmentStatus.Bad
        ):
            log.info(
                f"skipped to delete environment {environment.name}, "
                "as on runbook, keep_environment value "
                f"is set to {self.runbook.keep_environment} "
                f"and env status is {environment.status}"
            )
            environment.status = EnvironmentStatus.Deleted
            # output addresses for troubleshooting easier.
            remote_addresses = [
                x.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS]
                for x in environment.nodes.list()
                if isinstance(x, RemoteNode) and hasattr(x, "_connection_info")
            ]
            # if the connection info is not found, there is no ip address to
            # output.
            if remote_addresses:
                log.info(f"node ip addresses: {remote_addresses}")
        else:
            environment.status = EnvironmentStatus.Deleted
            self._delete_environment(environment, log)

    def cleanup(self) -> None:
        self._cleanup()

    def _initialize_guest_nodes(self, node: Node) -> None:
        platform_runbook = cast(schema.Platform, self.runbook)

        if not platform_runbook.guests:
            raise LisaException(
                "guests must be defined in the platform runbook, "
                "when guest_enabled is True."
            )

        for guest_runbook in platform_runbook.guests:
            guest_runbook = cast(schema.GuestNode, guest_runbook)
            # follow parent capability, so it can pass requirements validations.
            guest_runbook.capability = node.capability
            guest_node = node.create(
                index=len(node.guests),
                runbook=guest_runbook,
                logger_name="g",
                parent=node,
            )
            node.guests.append(guest_node)


def load_platform(platforms_runbook: List[schema.Platform]) -> Platform:
    log = _get_init_logger()
    # we may extend it later to support multiple platforms
    platform_count = len(platforms_runbook)
    if platform_count != 1:
        raise LisaException("There must be 1 and only 1 platform")

    factory = subclasses.Factory[Platform](Platform)
    default_platform: Platform = factory.create_by_runbook(runbook=platforms_runbook[0])
    log.debug(f"activated platform '{default_platform.type_name()}'")

    return default_platform


def load_platform_from_builder(runbook_builder: RunbookBuilder) -> Platform:
    platform_runbook_data = runbook_builder.partial_resolve(constants.PLATFORM)
    platform_runbook = schema.load_by_type_many(schema.Platform, platform_runbook_data)
    platform = load_platform(platform_runbook)
    return platform
