from pathlib import Path
from typing import Dict, List, Optional, cast

from singleton_decorator import singleton  # type: ignore

from lisa.util import constants


@singleton
class Config(Dict[str, object]):
    def __init__(
        self,
        base_path: Optional[Path] = None,
        config: Optional[Dict[str, object]] = None,
    ) -> None:
        if base_path is not None:
            self.base_path = base_path
        if config is not None:
            self.config: Dict[str, object] = config

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
