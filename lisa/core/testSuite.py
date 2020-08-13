from __future__ import annotations

from abc import ABCMeta
from typing import TYPE_CHECKING, List

from lisa.core.action import Action
from lisa.core.actionStatus import ActionStatus
from lisa.util.logger import log

if TYPE_CHECKING:
    from lisa.core.environment import Environment
    from lisa.core.testFactory import TestSuiteData


class TestSuite(Action, metaclass=ABCMeta):
    def __init__(
        self, environment: Environment, cases: List[str], testsuite_data: TestSuiteData,
    ) -> None:
        self.environment = environment
        # test cases to run, must be a test method in this class.
        self.cases = cases
        self.testsuite_data = testsuite_data

        self._should_stop = False

    @property
    def skiprun(self) -> bool:
        return False

    def before_suite(self) -> None:
        pass

    def after_suite(self) -> None:
        pass

    def before_case(self) -> None:
        pass

    def after_case(self) -> None:
        pass

    @property
    def typename(self) -> str:
        return "TestSuite"

    async def start(self) -> None:
        if self.skiprun:
            log.info(f"suite[{self.testsuite_data.name}] skipped on this run")
            return
        self.before_suite()
        for test_case in self.cases:
            self.before_case()
            test_method = getattr(self, test_case)
            test_method()
            self.after_case()
            if self._should_stop:
                log.info("received stop message, stop run")
                self.set_status(ActionStatus.STOPPED)
                break
        self.after_suite()

    async def stop(self) -> None:
        self.set_status(ActionStatus.STOPPING)
        self._should_stop = True

    async def close(self) -> None:
        pass
