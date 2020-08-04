from lisa.util import constants
from lisa.common.logger import log
from .platform import Platform
from typing import Dict


class PlatformFactory:
    def __init__(self):
        self.platforms: Dict[str, Platform] = dict()

    def registerPlatform(self, platform):
        platform_type = platform.platformType(platform).lower()
        if self.platforms.get(platform_type) is None:
            self.platforms[platform_type] = platform()
        else:
            raise Exception("platform '%s' exists, cannot be registered again")

    def initializePlatform(self, config):
        # we may extend it later to support multiple platforms
        platform_count = len(config)
        if platform_count != 1:
            raise Exception("There must be 1 and only 1 platform")

        platform_type = config[0].get("type")
        if platform_type is None:
            raise Exception("type of platfrom shouldn't be None")

        self._buildFactory()
        log.debug(
            "registered platforms [%s]",
            ", ".join([name for name in self.platforms.keys()]),
        )

        platform = self.platforms.get(platform_type.lower())
        if platform is None:
            raise Exception("cannot find platform type '%s'" % platform_type)
        log.info("activated platform '%s'", platform_type)

        platform.config(constants.CONFIG_CONFIG, config[0])
        return platform

    def _buildFactory(self):
        for sub_class in Platform.__subclasses__():
            self.registerPlatform(sub_class)


platform_factory = PlatformFactory()
