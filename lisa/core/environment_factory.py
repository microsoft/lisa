from typing import Dict, List, Optional, cast

from lisa.util import constants

from .environment import Environment

default_no_name = "_no_name_default"


class EnvironmentsFactory:
    def __init__(self):
        self.environments: Dict[str, Environment] = dict()
        self.maxConcurrency = 1

    def loadEnvironments(self, config: Dict[str, object]):
        maxConcurrency = config.get(constants.ENVIRONMENT_MAX_CONCURRENDCY)
        if maxConcurrency is not None:
            self.maxConcurrency = maxConcurrency
        environments_config = cast(
            List[Dict[str, object]], config.get(constants.ENVIRONMENTS)
        )
        without_name: bool = False
        for environment_config in environments_config:
            environment = Environment.loadEnvironment(environment_config)
            if environment.name is None:
                if without_name is True:
                    raise Exception("at least two environments has no name")
                environment.name = default_no_name
                without_name = True
            self.environments[environment.name] = environment

    def getEnvironment(self, name: Optional[str] = None) -> Environment:
        if name is None:
            key = default_no_name
        else:
            key = name.lower()
        environmet = self.environments.get(key)
        if environmet is None:
            raise Exception("not found environment '%s'", name)

        return environmet


environment_factory = EnvironmentsFactory()
