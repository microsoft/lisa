# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from typing import Any, List, Optional, Type

from dataclasses_json import dataclass_json

from lisa import feature, features
from lisa.environment import Environment, EnvironmentStatus
from lisa.feature import Feature
from lisa.platform_ import Platform
from lisa.util.logger import Logger

from . import READY


@dataclass_json()
@dataclass
class ReadyPlatformSchema:
    # If set to True, a dirty environment will be retained and reused
    # instead of being deleted and recreated.
    reuse_dirty_env: bool = field(default=True)
    platform_hint: Optional[str] = field(default=None)


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
        ]

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        if environment.runbook.nodes_requirement:
            log.warn_or_raise(
                environment.warn_as_error,
                "ready platform cannot process environment with requirement",
            )

        detected_platform = self._detect_platform(environment, log)
        log.info(f"Detected platform: {detected_platform}")

        platform_class = self._get_platform_class(detected_platform)
        supported_features = platform_class.supported_features()

        for node in environment.nodes.list():
            feature.reload_platform_features(node.capability, supported_features)
            log.debug(
                f"Reloaded {len(supported_features)} features for {detected_platform}"
            )

        return len(environment.nodes) > 0

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

    def _detect_platform(self, environment: Environment, log: Logger) -> str:
        if self._ready_runbook.platform_hint:
            return self._ready_runbook.platform_hint.lower()

        node = environment.nodes[0]
        try:
            result = node.execute(
                "curl -s -H Metadata:true http://169.254.169.254/metadata/instance?"
                "api-version=2021-02-01",
                timeout=5,
                shell=True,
            )
            if "azure" in result.stdout.lower():
                return "azure"
        except Exception:
            pass

        try:
            result = node.execute(
                "curl -s http://169.254.169.254/latest/meta-data/", timeout=5
            )
            if "ami-id" in result.stdout or "instance-id" in result.stdout:
                return "aws"
        except Exception:
            pass

        return "generic"

    def _get_platform_class(self, platform_name: str) -> Type[Platform]:
        from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
        from lisa.sut_orchestrator.aws.platform_ import AwsPlatform

        mapping = {
            "azure": AzurePlatform,
            "aws": AwsPlatform,
            "generic": ReadyPlatform,
        }

        platform_class = mapping.get(platform_name, ReadyPlatform)
        if platform_class is None:
            platform_class = ReadyPlatform
        return platform_class
