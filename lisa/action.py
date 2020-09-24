from __future__ import annotations

from abc import ABCMeta, abstractmethod
from enum import Enum

from lisa.util import LisaException
from lisa.util.logger import get_logger
from lisa.util.perf_timer import create_timer

ActionStatus = Enum(
    "ActionStatus",
    [
        "UNINITIALIZED",
        "INITIALIZING",
        "INITIALIZED",
        "WAITING",
        "RUNNING",
        "SUCCESS",
        "FAILED",
        "STOPPING",
        "STOPPED",
        "UNKNOWN",
    ],
)


class Action(metaclass=ABCMeta):
    def __init__(self) -> None:
        self.name: str = self.__class__.__name__
        self.log = get_logger("Action")

        self.__status = ActionStatus.UNINITIALIZED
        self.__is_started = False
        self.__timer = create_timer()

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

    def get_status(self) -> ActionStatus:
        return self.__status

    def set_status(self, status: ActionStatus) -> None:
        if self.__status != status:
            self.log.debug(
                f"{self.name} status changed from {self.__status.name} "
                f"to {status.name} with {self.__timer}"
            )
            self.__timer = create_timer()
        self.__status = status

    def validate_started(self) -> None:
        if not self.__is_started:
            raise LisaException(f"action[{self.name}] is not started yet.")
