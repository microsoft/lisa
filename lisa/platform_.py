from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, List, Optional, Type, cast

from lisa.util import constants
from lisa.util.exceptions import LisaException
from lisa.util.logger import get_logger

if TYPE_CHECKING:
    from lisa.environment import Environment


class Platform(ABC):
    @classmethod
    @abstractmethod
    def platform_type(cls) -> str:
        raise NotImplementedError()

    @abstractmethod
    def config(self, key: str, value: object) -> None:
        pass

    @abstractmethod
    def _request_environment_internal(self, environment: Environment) -> Environment:
        raise NotImplementedError()

    @abstractmethod
    def _delete_environment_internal(self, environment: Environment) -> None:
        raise NotImplementedError()

    def request_environment(self, environment: Environment) -> Environment:
        environment = self._request_environment_internal(environment)
        environment.is_ready = True
        return environment

    def delete_environment(self, environment: Environment) -> None:
        environment.close()
        self._delete_environment_internal(environment)
        environment.is_ready = False


class Platforms(Dict[str, Platform]):
    def __init__(self) -> None:
        self._default: Optional[Platform] = None

    @property
    def default(self) -> Platform:
        assert self._default
        return self._default

    @default.setter
    def default(self, value: Platform) -> None:
        self._default = value

    def register_platform(self, platform: Type[Platform]) -> None:
        platform_type = platform.platform_type().lower()
        if platforms.get(platform_type) is None:
            platforms[platform_type] = platform()
        else:
            raise LisaException(
                f"platform '{platform_type}' exists, cannot be registered again"
            )


def initialize_platforms(config: List[Dict[str, object]]) -> None:
    if not config:
        raise LisaException("cannot find platform")

    # we may extend it later to support multiple platforms
    platform_count = len(config)
    if platform_count != 1:
        raise LisaException("There must be 1 and only 1 platform")
    platform_type = cast(Optional[str], config[0].get(constants.TYPE))
    if platform_type is None:
        raise LisaException("type of platfrom shouldn't be None")

    for sub_class in Platform.__subclasses__():
        platform_class = cast(Type[Platform], sub_class)
        platforms.register_platform(platform_class)
    log = get_logger("init", "platform")
    log.debug(
        f"registered platforms: " f"[{', '.join([name for name in platforms.keys()])}]"
    )

    platform = platforms.get(platform_type.lower())
    if platform is None:
        raise LisaException(f"cannot find platform type '{platform_type}'")
    log.info(f"activated platform '{platform_type}'")

    platform.config(constants.CONFIG_CONFIG, config[0])
    platforms.default = platform


platforms = Platforms()
