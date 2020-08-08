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

    def getExtension(self) -> Dict[str, object]:
        return self._getAndCast(constants.EXTENSION)

    def getEnvironment(self) -> Dict[str, object]:
        return self._getAndCast(constants.ENVIRONMENT)

    def getPlatform(self) -> List[Dict[str, object]]:
        return cast(
            List[Dict[str, object]], self.config.get(constants.PLATFORM, list())
        )

    def getTestCase(self) -> Dict[str, object]:
        return self._getAndCast(constants.TESTCASE)

    # TODO: This is a hack to get around our data not being
    # structured. Since we generally know the type of the data we’re
    # trying to get, this indicates that we need to properly structure
    # said data. Doing so correctly will enable us to delete this.
    def _getAndCast(self, name: str) -> Dict[str, object]:
        return cast(Dict[str, object], self.config.get(name, dict()))
