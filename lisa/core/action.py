from __future__ import annotations

from abc import ABCMeta, abstractmethod
from typing import Dict

from lisa.core.actionStatus import ActionStatus
from lisa.util.logger import log
from lisa.util.exceptions import LisaException


class Action(metaclass=ABCMeta):
    def __init__(self) -> None:
        self.__status = ActionStatus.UNINITIALIZED
        self.name: str = self.__class__.__name__
        self.isStarted = False

    def config(self, key: str, value: object) -> None:
        pass

    @abstractmethod
    def getTypeName(self) -> str:
        raise NotImplementedError()

    @abstractmethod
    async def start(self) -> None:
        self.isStarted = True
        self.setStatus(ActionStatus.RUNNING)

    @abstractmethod
    async def stop(self) -> None:
        self.validateStarted()

    @abstractmethod
    async def close(self) -> None:
        self.validateStarted()

    def getStatus(self) -> ActionStatus:
        return self.__status

    def setStatus(self, status: ActionStatus) -> None:
        if self.__status != status:
            log.info(
                f"{self.name} status changed from {self.__status.name} to {status.name}"
            )
        self.__status = status

    def validateStarted(self) -> None:
        if not self.isStarted:
            raise LisaException("action is not started yet.")

    def getPrerequisites(self) -> None:
        return None

    # TODO to validate action specified configs
    def validateConfig(self, config: Dict[str, object]) -> None:
        pass
