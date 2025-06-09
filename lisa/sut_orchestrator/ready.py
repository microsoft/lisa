# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Type

from dataclasses_json import dataclass_json

from lisa import feature, features
from lisa.environment import Environment, EnvironmentStatus
from lisa.feature import Feature
from lisa.platform_ import Platform
from lisa.schema import DiskOptionSettings, NetworkInterfaceOptionSettings
from lisa.util.logger import Logger

from . import READY


@dataclass_json()
@dataclass
class ReadyPlatformSchema:
    # If set to True, a dirty environment will be retained and reused
    # instead of being deleted and recreated.
    reuse_dirty_env: bool = field(default=True)


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
        if self._ready_runbook.reuse_dirty_env:
            log.debug(
                f"Environment '{environment.name}' was marked as 'Deleted' "
                "because it was dirty. Now resetting it to 'Prepared' since "
                "'reuse_dirty_env' is true, allowing test cases to reuse "
                "the environment."
            )
            environment.status = EnvironmentStatus.Prepared


class SerialConsole(features.SerialConsole):
    def _get_console_log(self, saved_path: Optional[Path]) -> bytes:
        return b""

    def read(self) -> str:
        return ""

    def write(self, data: str | List[str]) -> None:
        pass
