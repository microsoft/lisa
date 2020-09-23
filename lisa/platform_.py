from __future__ import annotations

from abc import ABC, abstractmethod
from collections import UserDict
from functools import partial
from typing import TYPE_CHECKING, Any, List, Optional, Type, cast

from lisa import schema
from lisa.environment import Environments
from lisa.feature import Feature, Features
from lisa.util import InitializableMixin, LisaException, constants
from lisa.util.logger import Logger, get_logger
from lisa.util.perf_timer import create_timer

if TYPE_CHECKING:
    from lisa.environment import Environment

_get_init_logger = partial(get_logger, "init", "platform")


class WaitMoreResourceError(Exception):
    pass


class Platform(ABC, InitializableMixin):
    def __init__(self) -> None:
        super().__init__()
        self._log = get_logger("", self.platform_type())

    @classmethod
    @abstractmethod
    def platform_type(cls) -> str:
        raise NotImplementedError()

    @classmethod
    @abstractmethod
    def supported_features(cls) -> List[Type[Feature]]:
        """
        Indicates which feature classes should be used to instance a feature.

        For example, StartStop needs platform implemention, and LISA doesn't know which
        type uses to start/stop for Azure. So Azure platform needs to return a type
        like azure.StartStop. The azure.StartStop use same feature string as
        lisa.features.StartStop. When test cases reference a feature by string, it can
        be instanced to azure.StartStop.
        """
        raise NotImplementedError()

    @abstractmethod
    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        """
        What to be prepared for an environment
        1. check if platform can meet requirement of this environment
        2. if #1 is yes, specified platform context,
            so that the environment can be created in deploy phase
            with same spec as prepared.
        3. set cost for environment priority.

        return True, if environment can be deployed. False, if cannot.
        """
        raise NotImplementedError()

    @abstractmethod
    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        raise NotImplementedError()

    @abstractmethod
    def _delete_environment(self, environment: Environment, log: Logger) -> None:
        raise NotImplementedError()

    def _config(self, key: str, value: object) -> None:
        pass

    def _initialize(self) -> None:
        """
        Uses to do some initialization work.
        It will be called when first environment is requested.
        """
        pass

    def config(self, key: str, value: Any) -> None:
        if key == constants.CONFIG_RUNBOOK:
            # store platform runbook.
            self._runbook: schema.Platform = value
        self._config(key, value)

    def prepare_environments(self, environments: Environments) -> List[Environment]:
        """
        return prioritized environments.
            user defined environment is higher priority than test cases,
            and then lower cost is prior to higher.
        """
        self.initialize()

        prepared_environments: List[Environment] = []
        for environment in environments.values():
            log = get_logger(f"prepare[{environment.name}]", parent=self._log)
            is_success = self._prepare_environment(environment, log)
            if is_success:
                prepared_environments.append(environment)
            else:
                log.debug("dropped since no fit capability found")

        # sort by environment source and cost cases
        # user defined should be higher priority than test cases' requirement
        prepared_environments.sort(key=lambda x: (not x.is_predefined, x.cost))

        return prepared_environments

    def deploy_environment(self, environment: Environment) -> None:
        log = get_logger(f"deploy[{environment.name}]", parent=self._log)
        log.info("depolying")
        timer = create_timer()
        self._deploy_environment(environment, log)
        log.debug("initializing environment")
        environment.initialize()
        # initialize features
        # features may need platform, so create it in platform
        for node in environment.nodes.list():
            node.features = Features(node, self)
        log.info(f"deployed with {timer}")

    def delete_environment(self, environment: Environment) -> None:
        log = get_logger(f"del[{environment.name}]", parent=self._log)
        log.debug("deleting")
        environment.close()
        self._delete_environment(environment, log)
        environment.is_ready = False
        log.debug("deleted")


if TYPE_CHECKING:
    PlatformsDict = UserDict[str, Platform]
else:
    PlatformsDict = UserDict


class Platforms(PlatformsDict):
    def __init__(self) -> None:
        super().__init__()
        self._default: Optional[Platform] = None

    @property
    def default(self) -> Platform:
        assert self._default
        return self._default

    @default.setter
    def default(self, value: Platform) -> None:
        self._default = value

    def register_platform(self, platform: Type[Platform]) -> None:
        platform_type = platform.platform_type()
        exist_platform = self.get(platform_type)
        if exist_platform:
            # so far, it happens on ut only. As global variables are used in ut,
            # it's # important to use first registered.
            log = _get_init_logger()
            log.warning(
                f"ignore to register [{platform_type}] platform again. "
                f"new: [{platform}], exist: [{exist_platform}]"
            )
        else:
            self[platform_type] = platform()


def _load_sub_platforms() -> Platforms:
    platforms = Platforms()
    for sub_class in Platform.__subclasses__():
        platform_class = cast(Type[Platform], sub_class)
        platforms.register_platform(platform_class)
    log = _get_init_logger()
    log.debug(
        f"registered platforms: " f"[{', '.join([name for name in platforms.keys()])}]"
    )
    return platforms


def load_platform(platforms_runbook: List[schema.Platform]) -> Platform:
    log = _get_init_logger()
    # we may extend it later to support multiple platforms
    platform_count = len(platforms_runbook)
    if platform_count != 1:
        raise LisaException("There must be 1 and only 1 platform")

    platforms = _load_sub_platforms()
    default_platform: Optional[Platform] = None
    for platform_runbook in platforms_runbook:
        platform_type = platform_runbook.type

        platform = platforms.get(platform_type)
        if platform is None:
            raise LisaException(f"cannot find platform type '{platform_type}'")

        if default_platform is None:
            default_platform = platform
            log.info(f"activated platform '{platform_type}'")
        platform.config(constants.CONFIG_RUNBOOK, platform_runbook)
    assert default_platform
    return default_platform
