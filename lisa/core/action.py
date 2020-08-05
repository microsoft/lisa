from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict

from lisa.common.logger import log


class ActionStatus(Enum):
    UNINITIALIZED = 1
    INITIALIZING = 2
    INITIALIZED = 3
    WAITING = 4
    RUNNING = 5
    SUCCESS = 6
    FAILED = 7
    STOPPING = 8
    STOPPED = 9
    UNKNOWN = 10


class Action(ABC):
    def __init__(self):
        self.__status = ActionStatus.UNINITIALIZED
        self.__name = None
        self.isStarted = False

    def config(self, key: str, value: object):
        pass

    @property
    def name(self):
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

    def validateStarted(self):
        if not self.isStarted:
            raise Exception("action is not started yet.")

    def getPrerequisites(self):
        return None

    # TODO to validate action specified configs
    def validateConfig(self, config: Dict[str, object]) -> None:
        pass
