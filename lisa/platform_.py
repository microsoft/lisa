from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, List, Optional, Type, cast

from lisa.util import constants
from lisa.util.exceptions import LisaException
from lisa.util.logger import get_logger

if TYPE_CHECKING:
    from lisa.environment import Environment


_platforms: Dict[str, Platform] = dict()
_current: Optional[Platform] = None


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
        raise NotImplementedError

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


def get_platforms() -> Dict[str, Platform]:
    return _platforms


def get_current() -> Platform:
    assert _current
    return _current


def initialize_platform(config: List[Dict[str, object]]) -> None:
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
        _register_platform(platform_class)
    log = get_logger("init", "platform")
    log.debug(
        f"registered platforms: " f"[{', '.join([name for name in _platforms.keys()])}]"
    )

    platform = _platforms.get(platform_type.lower())
    if platform is None:
        raise LisaException(f"cannot find platform type '{platform_type}'")
    log.info(f"activated platform '{platform_type}'")

    platform.config(constants.CONFIG_CONFIG, config[0])
    global _current
    _current = platform


def _register_platform(platform: Type[Platform]) -> None:
    platform_type = platform.platform_type().lower()
    if _platforms.get(platform_type) is None:
        _platforms[platform_type] = platform()
    else:
        raise LisaException(
            f"platform '{platform_type}' exists, cannot be registered again"
        )
