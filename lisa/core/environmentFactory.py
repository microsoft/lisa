from typing import Dict, List, Optional, cast

from singleton_decorator import singleton  # type: ignore

from lisa.core.environment import Environment
from lisa.util import constants
from lisa.util.exceptions import LisaException


@singleton
class EnvironmentFactory:
    _default_no_name = "_no_name_default"

    def __init__(self) -> None:
        self.environments: Dict[str, Environment] = dict()
        self.max_concurrency = 1

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
        for environment_config in environments_config:
            environment = Environment.load(environment_config)
            if environment.name is None:
                if without_name:
                    raise LisaException("at least two environments has no name")
                environment.name = self._default_no_name
                without_name = True
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
