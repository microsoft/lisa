from __future__ import annotations

from abc import ABC, abstractmethod
from collections import UserDict
from functools import partial
from typing import TYPE_CHECKING, Any, List, Optional, Type, cast

from lisa import schema
from lisa.util import LisaException, constants
from lisa.util.logger import get_logger

if TYPE_CHECKING:
    from lisa.environment import Environment

_get_init_logger = partial(get_logger, "init", "platform")


class Platform(ABC):
    def __init__(self) -> None:
        self._log = get_logger("platform", self.platform_type())
        self.__is_initialized = False

    @classmethod
    @abstractmethod
    def platform_type(cls) -> str:
        raise NotImplementedError()

    @property
    def platform_schema(self) -> Optional[Type[Any]]:
        return None

    @property
    def node_schema(self) -> Optional[Type[Any]]:
        return None

    def _config(self, key: str, value: object) -> None:
        pass

    def _initialize(self) -> None:
        """
        Uses to do some initialization work.
        It will be called when first environment is requested.
        """
        pass

    @abstractmethod
    def _request_environment(self, environment: Environment) -> Environment:
        raise NotImplementedError()

    @abstractmethod
    def _delete_environment(self, environment: Environment) -> None:
        raise NotImplementedError()

    def config(self, key: str, value: Any) -> None:
        if key == constants.CONFIG_RUNBOOK:
            # store platform runbook.
            self._runbook = cast(schema.Platform, value)
        self._config(key, value)

    def request_environment(self, environment: Environment) -> Environment:
        if not self.__is_initialized:
            self._log.debug("initializing...")
            self._initialize()
            self._is_initialized = True
            self._log.debug("initialized")

        self._log.info(f"requesting environment {environment.name}")
        environment = self._request_environment(environment)
        environment.is_ready = True
        self._log.info(f"requested environment {environment.name}")
        return environment

    def delete_environment(self, environment: Environment) -> None:
        self._log.debug(f"environment {environment.name} deleting")
        environment.close()
        self._delete_environment(environment)
        environment.is_ready = False
        self._log.debug(f"environment {environment.name} deleted")


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
        if platforms.get(platform_type) is None:
            platforms[platform_type] = platform()
        else:
            raise LisaException(
                f"platform '{platform_type}' exists, cannot be registered again"
            )


def load_platforms(platforms_runbook: List[schema.Platform]) -> None:
    log = _get_init_logger()
    # we may extend it later to support multiple platforms
    platform_count = len(platforms_runbook)
    if platform_count != 1:
        raise LisaException("There must be 1 and only 1 platform")

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
    platforms.default = default_platform


def initialize_platforms() -> None:
    for sub_class in Platform.__subclasses__():
        platform_class = cast(Type[Platform], sub_class)
        platforms.register_platform(platform_class)
    log = _get_init_logger()
    log.debug(
        f"registered platforms: " f"[{', '.join([name for name in platforms.keys()])}]"
    )


platforms = Platforms()
