# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List, Type

from lisa import features
from lisa.environment import Environment
from lisa.feature import Feature
from lisa.platform_ import Platform
from lisa.schema import DiskOptionSettings, NetworkInterfaceOptionSettings
from lisa.util.logger import Logger

from . import READY


class ReadyPlatform(Platform):
    @classmethod
    def type_name(cls) -> str:
        return READY

    @classmethod
    def supported_features(cls) -> List[Type[Feature]]:
        return [
            features.Disk,
            features.Gpu,
            features.Nvme,
            features.NestedVirtualization,
            features.NetworkInterface,
            features.Infiniband,
            features.Hibernation,
            features.IsolatedResource,
            features.Nfs,
        ]

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        if environment.runbook.nodes_requirement:
            log.warn_or_raise(
                environment.warn_as_error,
                "ready platform cannot process environment with requirement",
            )
        is_success: bool = False

        # Workaround the capability exception. If the disk or network
        # requirement is defined in a test case, the later check will fail. So
        # here is the place to set disk or network a default value, if it's
        # None.
        for node in environment.nodes.list():
            if node.capability.disk is None:
                node.capability.disk = DiskOptionSettings()
            if node.capability.network_interface is None:
                node.capability.network_interface = NetworkInterfaceOptionSettings()

        if len(environment.nodes):
            # if it has nodes, it's a good environment to run test cases
            is_success = True
        return is_success

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        # do nothing for deploy
        pass

    def _delete_environment(self, environment: Environment, log: Logger) -> None:
        # ready platform doesn't support delete environment
        pass
