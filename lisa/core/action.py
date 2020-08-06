from __future__ import annotations

from abc import ABCMeta, abstractmethod
from typing import Dict, Optional

from lisa.core.actionStatus import ActionStatus
from lisa.util.logger import log


class Action(metaclass=ABCMeta):
    def __init__(self) -> None:
        self.__status = ActionStatus.UNINITIALIZED
        self.__name: Optional[str] = None
        self.isStarted = False

    def config(self, key: str, value: object) -> None:
        pass

    @property
    def name(self) -> str:
        if self.__name is not None:
            name = self.__name
        else:
            name = self.__class__.__name__
        return name

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
    async def cleanup(self) -> None:
        self.validateStarted()

    def getStatus(self) -> ActionStatus:
        return self.__status

    def setStatus(self, status: ActionStatus) -> None:
        if self.__status != status:
            log.info(
                "%s status changed from %s to %s"
                % (self.name, self.__status.name, status.name)
            )
        self.__status = status

    def validateStarted(self) -> None:
        if not self.isStarted:
            raise Exception("action is not started yet.")

    def getPrerequisites(self) -> None:
        return None

    # TODO to validate action specified configs
    def validateConfig(self, config: Dict[str, object]) -> None:
        pass
