from lisa.common.logger import log
from lisa.core.action import ActionStatus
from typing import List
from lisa import Action
from .environment import Environment
from abc import ABC


class TestSuite(Action, ABC):
    area: str = ""
    category: str = ""
    tags: List[str] = []

    def __init__(self, environment: Environment, cases: List[str]):
        self.environment = environment
        self.cases = cases
        self.shouldStop = False

    def setup(self):
        pass

    def cleanup(self):
        pass

    def beforeCase(self):
        pass

    def afterCase(self):
        pass

    def getTypeName(self):
        return "TestSuite"

    async def start(self):
        self.setup()
        for test_case in self.cases:
            self.beforeCase()
            test_method = getattr(self, test_case)
            test_method(self)
            self.afterCase()
            if self.shouldStop:
                log.info("received stop message, stop run")
                self.setStatus(ActionStatus.STOPPED)
                break
        self.cleanup()

    async def stop(self):
        self.setStatus(ActionStatus.STOPPING)
        self.shouldStop = True
