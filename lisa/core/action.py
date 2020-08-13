from __future__ import annotations

from abc import ABCMeta, abstractmethod
from typing import Dict

from lisa.core.actionStatus import ActionStatus
from lisa.util.exceptions import LisaException
from lisa.util.logger import log


class Action(metaclass=ABCMeta):
    def __init__(self) -> None:
        self.name: str = self.__class__.__name__

        self.__status = ActionStatus.UNINITIALIZED
        self.__is_started = False

    def config(self, key: str, value: object) -> None:
        pass

    @property
    @abstractmethod
    def typename(self) -> str:
        raise NotImplementedError()

    @abstractmethod
    async def start(self) -> None:
        self.__is_started = True
        self.set_status(ActionStatus.RUNNING)

    @abstractmethod
    async def stop(self) -> None:
        self.validate_started()

    @abstractmethod
    async def close(self) -> None:
        self.validate_started()

    @property
    def prerequisites(self) -> None:
        return None

    def get_status(self) -> ActionStatus:
        return self.__status

    def set_status(self, status: ActionStatus) -> None:
        if self.__status != status:
            log.info(
                f"{self.name} status changed from {self.__status.name} to {status.name}"
            )
        self.__status = status

    def validate_started(self) -> None:
        if not self.__is_started:
            raise LisaException(f"action[{self.name}] is not started yet.")

    def validate_config(self, config: Dict[str, object]) -> None:
        # TODO to validate action specified configs
        pass
