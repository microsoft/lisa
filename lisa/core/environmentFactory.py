from typing import Dict, List, Optional, cast

from singleton_decorator import singleton  # type: ignore

from lisa.core.environment import Environment
from lisa.util import constants


@singleton
class EnvironmentFactory:
    default_no_name = "_no_name_default"

    def __init__(self) -> None:
        self.environments: Dict[str, Environment] = dict()
        self.maxConcurrency = 1

    def loadEnvironments(self, config: Dict[str, object]) -> None:
        if not config:
            raise Exception("environment section must be set in config")
        maxConcurrency = cast(
            Optional[int], config.get(constants.ENVIRONMENT_MAX_CONCURRENDCY)
        )
        if maxConcurrency is not None:
            self.maxConcurrency = maxConcurrency
        environments_config = cast(
            List[Dict[str, object]], config.get(constants.ENVIRONMENTS)
        )
        without_name: bool = False
        for environment_config in environments_config:
            environment = Environment.loadEnvironment(environment_config)
            if environment.name is None:
                if without_name:
                    raise Exception("at least two environments has no name")
                environment.name = self.default_no_name
                without_name = True
            self.environments[environment.name] = environment

    def getEnvironment(self, name: Optional[str] = None) -> Environment:
        if name is None:
            key = self.default_no_name
        else:
            key = name.lower()
        environmet = self.environments.get(key)
        if environmet is None:
            raise Exception(f"not found environment '{name}'")

        return environmet
