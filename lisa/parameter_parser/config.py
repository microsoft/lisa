from typing import Dict, Optional, cast

from lisa.util import constants


class Config(dict):
    def __init__(self, config: Dict[str, object]):
        self.config: Dict[str, object] = config

    def validate(self):
        # TODO implement config validation
        pass

    def getExtension(self) -> Optional[Dict[str, object]]:
        return self._getAndCast(constants.EXTENSION)

    def getEnvironment(self) -> Optional[Dict[str, object]]:
        return self._getAndCast(constants.ENVIRONMENT)

    def getPlatform(self) -> Optional[Dict[str, object]]:
        return self._getAndCast(constants.PLATFORM)

    def getTestCase(self) -> Optional[Dict[str, object]]:
        return self._getAndCast(constants.TESTCASE)

    def _getAndCast(self, name: str) -> Optional[Dict[str, object]]:
        return cast(Optional[Dict[str, object]], self.config.get(name))
