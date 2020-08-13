from typing import Dict, List, Optional, Type, cast

from singleton_decorator import singleton  # type: ignore

from lisa.core.platform import Platform
from lisa.util import constants
from lisa.util.exceptions import LisaException
from lisa.util.logger import log


@singleton
class PlatformFactory:
    def __init__(self) -> None:
        self.platforms: Dict[str, Platform] = dict()
        self.current: Optional[Platform] = None

    def initialize_platform(self, config: List[Dict[str, object]]) -> None:
        if not config:
            raise LisaException("cannot find platform")

        # we may extend it later to support multiple platforms
        platform_count = len(config)
        if platform_count != 1:
            raise LisaException("There must be 1 and only 1 platform")
        platform_type = cast(Optional[str], config[0].get(constants.TYPE))
        if platform_type is None:
            raise LisaException("type of platfrom shouldn't be None")

        self._build_factory()
        log.debug(
            f"registered platforms: "
            f"[{', '.join([name for name in self.platforms.keys()])}]"
        )

        platform = self.platforms.get(platform_type.lower())
        if platform is None:
            raise LisaException(f"cannot find platform type '{platform_type}'")
        log.info(f"activated platform '{platform_type}'")

        platform.config(constants.CONFIG_CONFIG, config[0])
        self.current = platform

    def _register_platform(self, platform: Type[Platform]) -> None:
        platform_type = platform.platform_type().lower()
        if self.platforms.get(platform_type) is None:
            self.platforms[platform_type] = platform()
        else:
            raise LisaException(
                f"platform '{platform_type}' exists, cannot be registered again"
            )

    def _build_factory(self) -> None:
        for sub_class in Platform.__subclasses__():
            platform_class = cast(Type[Platform], sub_class)
            self._register_platform(platform_class)
