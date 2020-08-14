from logging import Logger
from typing import Dict, List, Optional, cast

from lisa.core.environment import Environment
from lisa.util import constants
from lisa.util.exceptions import LisaException
from lisa.util.logger import get_logger


class EnvironmentFactory:
    _default_no_name = "_no_name_default"

    def __init__(self) -> None:
        self.environments: Dict[str, Environment] = dict()
        self.max_concurrency = 1

        self._log: Logger

    def load_environments(self, config: Dict[str, object]) -> None:
        if not config:
            raise LisaException("environment section must be set in config")
        max_concurrency = cast(
            Optional[int], config.get(constants.ENVIRONMENT_MAX_CONCURRENDCY)
        )
        if max_concurrency is not None:
            self.max_concurrency = max_concurrency
        environments_config = cast(
            List[Dict[str, object]], config.get(constants.ENVIRONMENTS)
        )
        without_name: bool = False
        self._initialize_logger()
        for environment_config in environments_config:
            environment = Environment.load(environment_config)
            if not environment.name:
                if without_name:
                    raise LisaException("at least two environments has no name")
                environment.name = self._default_no_name
                without_name = True
            self._log.info(f"loaded environment {environment.name}")
            self.environments[environment.name] = environment

    def get_environment(self, name: Optional[str] = None) -> Environment:
        if name is None:
            key = self._default_no_name
        else:
            key = name.lower()
        environment = self.environments.get(key)
        if environment is None:
            raise LisaException(f"not found environment '{name}'")

        return environment

    def _initialize_logger(self) -> None:
        if not hasattr(self, "_log"):
            self._log = get_logger("init", "env")


factory = EnvironmentFactory()
