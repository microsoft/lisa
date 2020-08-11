from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lisa.core.environment import Environment


class Platform(ABC):
    @classmethod
    @abstractmethod
    def platformType(cls) -> str:
        raise NotImplementedError()

    @abstractmethod
    def config(self, key: str, value: object) -> None:
        pass

    @abstractmethod
    def requestEnvironmentInternal(self, environment: Environment) -> Environment:
        raise NotImplementedError

    @abstractmethod
    def deleteEnvironmentInternal(self, environment: Environment) -> None:
        raise NotImplementedError()

    def requestEnvironment(self, environment: Environment) -> Environment:
        environment = self.requestEnvironmentInternal(environment)
        environment.isReady = True
        return environment

    def deleteEnvironment(self, environment: Environment) -> None:
        environment.close()
        self.deleteEnvironmentInternal(environment)
        environment.isReady = False
