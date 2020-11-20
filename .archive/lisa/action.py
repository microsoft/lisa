from __future__ import annotations

from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from enum import Enum

from lisa import notifier
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


@dataclass
class ActionMessage(notifier.MessageBase):
    type: str = "Action"
    sub_type: str = ""
    status: ActionStatus = ActionStatus.UNKNOWN
    total_elapsed: float = 0


class Action(metaclass=ABCMeta):
    def __init__(self) -> None:
        self.name: str = self.__class__.__name__
        self.log = get_logger("Action")

        self.__status = ActionStatus.UNINITIALIZED
        self.__is_started = False
        self.__timer = create_timer()
        self.__total: float = 0

    @abstractmethod
    async def start(self) -> None:
        self.__is_started = True
        self.status = ActionStatus.RUNNING

    @abstractmethod
    async def stop(self) -> None:
        self.validate_started()

    @abstractmethod
    async def close(self) -> None:
        self.validate_started()

    @property
    def status(self) -> ActionStatus:
        """The Action's current state, for example, 'UNINITIALIZED'."""
        return self.__status

    @status.setter
    def status(self, value: ActionStatus) -> None:
        if self.__status != value:
            self.log.debug(
                f"{self.name} status changed from {self.__status.name} "
                f"to {value.name} with {self.__timer}"
            )
            self.__total += self.__timer.elapsed()
            message = ActionMessage(
                elapsed=self.__timer.elapsed(),
                sub_type=self.name,
                status=value,
                total_elapsed=self.__total,
            )
            notifier.notify(message=message)
            self.__timer = create_timer()
            self.__status = value

    def validate_started(self) -> None:
        if not self.__is_started:
            raise LisaException(f"action[{self.name}] is not started yet.")
