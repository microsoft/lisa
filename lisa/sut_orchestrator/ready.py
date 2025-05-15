# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Type

from dataclasses_json import dataclass_json

from lisa import feature, features
from lisa.environment import Environment
from lisa.feature import Feature
from lisa.platform_ import Platform
from lisa.schema import DiskOptionSettings, NetworkInterfaceOptionSettings
from lisa.util.logger import Logger

from . import READY


@dataclass_json()
@dataclass
class ReadyPlatformSchema:
    # When set to True, the environment will not be deleted even if it becomes dirty.
    reuse_dirty_env: bool = True


class ReadyPlatform(Platform):
    @classmethod
    def type_name(cls) -> str:
        return READY

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        ready_runbook: ReadyPlatformSchema = self.runbook.get_extended_runbook(
            ReadyPlatformSchema
        )
        assert ready_runbook, "platform runbook cannot be empty"

        self._ready_runbook = ready_runbook

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
            features.SecurityProfile,
            features.SerialConsole,
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
            # Reload features to right types
            feature.reload_platform_features(node.capability, self.supported_features())

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

    def delete_environment(self, environment: Environment) -> None:
        # This is necessary when running multiple test cases that share the same
        # environment, as it avoids skipping later cases due to cleanup.
        if not self._ready_runbook.reuse_dirty_env:
            self._log.info(
                "The environment is marked as dirty but was not deleted, and will be"
                " reused by other test cases. Test results may be affected."
            )
            super().delete_environment(environment)


class SerialConsole(features.SerialConsole):
    def _get_console_log(self, saved_path: Optional[Path]) -> bytes:
        return b""

    def read(self) -> str:
        return ""

    def write(self, data: str) -> None:
        pass
