from lisa.core.environment import Environment
from abc import ABC, abstractclassmethod


class Platform(ABC):
    @abstractclassmethod
    def platformType(cls) -> str:
        pass

    def config(self, key: str, value: object):
        pass

    def requestEnvironment(self, environmentSpec):
        pass

    def deleteEnvironment(self, environment: Environment):
        pass
