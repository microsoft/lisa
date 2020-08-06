from __future__ import annotations

from abc import ABCMeta
from typing import TYPE_CHECKING, List

from lisa.common.logger import log
from lisa.core.action import Action, ActionStatus

if TYPE_CHECKING:
    from .environment import Environment


class TestSuite(Action, metaclass=ABCMeta):
    area: str = ""
    category: str = ""
    tags: List[str] = []

    def __init__(self, environment: Environment, cases: List[str]) -> None:
        self.environment = environment
        self.cases = cases
        self.shouldStop = False

    def suiteSetup(self) -> None:
        pass

    def suiteCleanup(self) -> None:
        pass

    def beforeCase(self) -> None:
        pass

    def afterCase(self) -> None:
        pass

    def getTypeName(self) -> str:
        return "TestSuite"

    async def start(self) -> None:
        self.suiteSetup()
        for test_case in self.cases:
            self.beforeCase()
            test_method = getattr(self, test_case)
            test_method()
            self.afterCase()
            if self.shouldStop:
                log.info("received stop message, stop run")
                self.setStatus(ActionStatus.STOPPED)
                break
        self.suiteCleanup()

    async def stop(self) -> None:
        self.setStatus(ActionStatus.STOPPING)
        self.shouldStop = True

    async def cleanup(self) -> None:
        pass
