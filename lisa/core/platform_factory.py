from lisa.common.logger import log
from .platform import Platform
from typing import Dict


class PlatformFactory:
    def __init__(self):
        self.platforms: Dict[str, Platform] = dict()

    def registerPlatform(self, platform):
        platform_type = platform.platformType(platform)
        if self.platforms.get(platform_type) is None:
            log.info(
                "registered platform '%s'", platform_type,
            )
            self.platforms[platform_type] = platform()
        else:
            # not sure what happens, subclass returns multiple items for
            #  same class
            # so just log debug level here.
            log.debug(
                "platform type '%s' already registered", platform_type,
            )

    def loadPlatform(self, type_name, config):
        pass


platformFactory = PlatformFactory()
