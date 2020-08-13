from __future__ import annotations

import unittest
from abc import ABCMeta
from typing import TYPE_CHECKING, List

from lisa.core.action import Action
from lisa.core.actionStatus import ActionStatus
from lisa.core.testResult import TestResult, TestStatus
from lisa.util.logger import log
from lisa.util.perf_timer import create_timer

if TYPE_CHECKING:
    from lisa.core.environment import Environment
    from lisa.core.testFactory import TestSuiteData


class TestSuite(Action, unittest.TestCase, metaclass=ABCMeta):
    def __init__(
        self,
        environment: Environment,
        case_results: List[TestResult],
        testsuite_data: TestSuiteData,
    ) -> None:
        self.environment = environment
        # test cases to run, must be a test method in this class.
        self.case_results = case_results
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
        suite_prefix = f"suite[{self.testsuite_data.name}]"
        if self.skiprun:
            log.info(f"{suite_prefix} skipped on this run")
            for case_result in self.case_results:
                case_result.status = TestStatus.SKIPPED
            return

        timer = create_timer()
        self.before_suite()
        log.debug(f"{suite_prefix} before_suite end with {timer}")

        for case_result in self.case_results:
            case_name = case_result.case.name
            case_prefix = f"case[{self.testsuite_data.name}.{case_name}]"
            test_method = getattr(self, case_name)

            log.info(f"{case_prefix} started")
            is_continue: bool = True
            total_timer = create_timer()

            timer = create_timer()
            try:
                self.before_case()
            except Exception as identifier:
                log.error(f"{case_prefix} before_case failed {identifier}")
                is_continue = False
            case_result.elapsed = timer.elapsed()
            log.debug(f"{case_prefix} before_case end with {timer}")

            if is_continue:
                timer = create_timer()
                try:
                    test_method()
                    case_result.status = TestStatus.PASSED
                except Exception as identifier:
                    log.error(f"{case_prefix} failed {identifier}")
                    case_result.status = TestStatus.FAILED
                    case_result.errorMessage = str(identifier)
                case_result.elapsed = timer.elapsed()
                log.debug(f"{case_prefix} method end with {timer}")
            else:
                case_result.status = TestStatus.SKIPPED
                case_result.errorMessage = f"{case_prefix} skipped as beforeCase failed"

            timer = create_timer()
            try:
                self.after_case()
            except Exception as identifier:
                log.error(f"{case_prefix} after_case failed {identifier}")
            log.debug(f"{case_prefix} after_case end with {timer}")

            case_result.elapsed = total_timer.elapsed()
            log.info(
                f"{case_prefix} result: {case_result.status.name}, "
                f"elapsed: {total_timer}"
            )
            if self._should_stop:
                log.info("received stop message, stop run")
                self.set_status(ActionStatus.STOPPED)
                break

        timer = create_timer()
        self.after_suite()
        log.debug(f"{suite_prefix} after_suite end with {timer}")

    async def stop(self) -> None:
        self.set_status(ActionStatus.STOPPING)
        self._should_stop = True

    async def close(self) -> None:
        pass
