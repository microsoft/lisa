from lisa.core.environment import Environment
from abc import ABC, abstractclassmethod


class Platform(ABC):
    @abstractclassmethod
    def platformType(cls) -> str:
        pass

    @abstractclassmethod
    def config(self, key: str, value: object):
        pass

    @abstractclassmethod
    def requestEnvironment(self, environmentSpec):
        pass

    @abstractclassmethod
    def deleteEnvironment(self, environment: Environment):
        pass
