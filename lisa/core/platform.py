from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lisa.core.environment import Environment


class Platform(ABC):
    @classmethod
    @abstractmethod
    def platform_type(cls) -> str:
        raise NotImplementedError()

    @abstractmethod
    def config(self, key: str, value: object) -> None:
        pass

    @abstractmethod
    def _request_environment_internal(self, environment: Environment) -> Environment:
        raise NotImplementedError

    @abstractmethod
    def _delete_environment_internal(self, environment: Environment) -> None:
        raise NotImplementedError()

    def request_environment(self, environment: Environment) -> Environment:
        environment = self._request_environment_internal(environment)
        environment.is_ready = True
        return environment

    def delete_environment(self, environment: Environment) -> None:
        environment.close()
        self._delete_environment_internal(environment)
        environment.is_ready = False
