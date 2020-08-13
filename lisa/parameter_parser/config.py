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
            self._config: Dict[str, object] = config

    def validate(self) -> None:
        # TODO implement config validation
        pass

    def get_extension(self) -> Dict[str, object]:
        return self._get_and_cast(constants.EXTENSION)

    def get_environment(self) -> Dict[str, object]:
        return self._get_and_cast(constants.ENVIRONMENT)

    def get_platform(self) -> List[Dict[str, object]]:
        return cast(
            List[Dict[str, object]], self._config.get(constants.PLATFORM, list())
        )

    def get_testcase(self) -> Dict[str, object]:
        return self._get_and_cast(constants.TESTCASE)

    # TODO: This is a hack to get around our data not being
    # structured. Since we generally know the type of the data we’re
    # trying to get, this indicates that we need to properly structure
    # said data. Doing so correctly will enable us to delete this.
    def _get_and_cast(self, name: str) -> Dict[str, object]:
        return cast(Dict[str, object], self._config.get(name, dict()))
