from abc import ABC, abstractmethod
from enum import Enum
from lisa.common import log


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
    def getTypeName(self):
        raise NotImplementedError()

    @abstractmethod
    def start(self):
        self.isStarted = True

    @abstractmethod
    def stop(self):
        self.validateStarted()

    @abstractmethod
    def cleanup(self):
        self.validateStarted()

    def getStatus(self):
        return self.__status

    def setStatus(self, status: ActionStatus):
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

    def validateParameters(self, parameters):
        pass

    def getPostValidation(self, parameters):
        return None
