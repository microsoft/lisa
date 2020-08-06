from typing import Dict, List, Optional, cast

from lisa.util import constants


class Config(Dict[str, object]):
    def __init__(self, base_path: str, config: Dict[str, object]) -> None:
        self.config: Dict[str, object] = config
        self.base_path = base_path

    def validate(self) -> None:
        # TODO implement config validation
        pass

    def getExtension(self) -> Optional[Dict[str, object]]:
        return self._getAndCast(constants.EXTENSION)

    def getEnvironment(self) -> Optional[Dict[str, object]]:
        return self._getAndCast(constants.ENVIRONMENT)

    def getPlatform(self) -> Optional[List[Dict[str, object]]]:
        return cast(
            Optional[List[Dict[str, object]]], self.config.get(constants.PLATFORM)
        )

    def getTestCase(self) -> Optional[Dict[str, object]]:
        return self._getAndCast(constants.TESTCASE)

    def _getAndCast(self, name: str) -> Optional[Dict[str, object]]:
        return cast(Optional[Dict[str, object]], self.config.get(name))
