from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, List

from lisa.common.logger import log
from lisa.core.action import Action, ActionStatus

if TYPE_CHECKING:
    from .environment import Environment


class TestSuite(Action, ABC):
    area: str = ""
    category: str = ""
    tags: List[str] = []

    def __init__(self, environment: Environment, cases: List[str]):
        self.environment = environment
        self.cases = cases
        self.shouldStop = False

    def suiteSetup(self):
        pass

    def suiteCleanup(self):
        pass

    def beforeCase(self):
        pass

    def afterCase(self):
        pass

    def getTypeName(self):
        return "TestSuite"

    async def start(self):
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

    async def stop(self):
        self.setStatus(ActionStatus.STOPPING)
        self.shouldStop = True

    async def cleanup(self):
        pass
