from __future__ import annotations

import unittest
from abc import ABCMeta
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Type

from lisa.action import Action, ActionStatus
from lisa.util.exceptions import LisaException
from lisa.util.logger import get_logger
from lisa.util.perf_timer import create_timer

if TYPE_CHECKING:
    from lisa.environment import Environment


TestStatus = Enum("TestStatus", ["NOTRUN", "RUNNING", "FAILED", "PASSED", "SKIPPED"])

_suites: Dict[str, TestSuiteData] = dict()
_cases: Dict[str, TestCaseData] = dict()


@dataclass
class TestResult:
    case: TestCaseData
    status: TestStatus = TestStatus.NOTRUN
    elapsed: float = 0
    errorMessage: str = ""


class TestSuiteMetadata:
    def __init__(
        self,
        area: str,
        category: str,
        description: str,
        tags: List[str],
        name: Optional[str] = None,
    ) -> None:
        self._area = area
        self._category = category
        self._tags = tags
        self._description = description
        self._name = name

    def __call__(self, test_class: Type[TestSuite]) -> Callable[..., object]:
        _add_test_class(
            test_class,
            self._area,
            self._category,
            self._description,
            self._tags,
            self._name,
        )

        def wrapper(
            test_class: Type[TestSuite],
            environment: Environment,
            cases: List[TestResult],
            metadata: TestSuiteData,
        ) -> TestSuite:
            return test_class(environment, cases, metadata)

        return wrapper


class TestCaseMetadata:
    def __init__(self, description: str, priority: Optional[int]) -> None:
        self._priority = priority
        self._description = description

    def __call__(self, func: Callable[..., None]) -> Callable[..., None]:
        _add_test_method(func, self._description, self._priority)

        def wrapper(*args: object) -> None:
            func(*args)

        return wrapper


class TestCaseData:
    def __init__(
        self,
        method: Callable[[], None],
        description: str,
        priority: Optional[int] = 2,
        name: str = "",
    ):
        if name is not None and name != "":
            self.name = name
        else:
            self.name = method.__name__
        self.full_name = method.__qualname__.lower()
        self.method = method
        self.description = description
        self.priority = priority
        self.suite: TestSuiteData

        self.key: str = self.name.lower()


class TestSuiteData:
    def __init__(
        self,
        test_class: Type[TestSuite],
        area: Optional[str],
        category: Optional[str],
        description: str,
        tags: List[str],
        name: str = "",
    ):
        self.test_class = test_class
        if name is not None and name != "":
            self.name: str = name
        else:
            self.name = test_class.__name__
        self.key = self.name.lower()
        self.area = area
        self.category = category
        self.description = description
        self.tags = tags
        self.cases: Dict[str, TestCaseData] = dict()

    def add_case(self, test_case: TestCaseData) -> None:
        if self.cases.get(test_case.key) is None:
            self.cases[test_case.key] = test_case
        else:
            raise LisaException(
                f"TestSuiteData has test method {test_case.key} already"
            )


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
        self._log = get_logger("suite", testsuite_data.name)

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
            self._log.info("skipped on this run")
            for case_result in self.case_results:
                case_result.status = TestStatus.SKIPPED
            return

        timer = create_timer()
        self.before_suite()
        self._log.debug(f"before_suite end with {timer}")

        #  replace to case's logger temporarily
        suite_log = self._log
        for case_result in self.case_results:
            case_name = case_result.case.name
            test_method = getattr(self, case_name)
            self._log = get_logger("case", f"{self.testsuite_data.name}.{case_name}")

            self._log.info("started")
            is_continue: bool = True
            total_timer = create_timer()

            timer = create_timer()
            try:
                self.before_case()
            except Exception as identifier:
                self._log.error("before_case failed", exc_info=identifier)
                is_continue = False
            case_result.elapsed = timer.elapsed()
            self._log.debug(f"before_case end with {timer}")

            if is_continue:
                timer = create_timer()
                try:
                    test_method()
                    case_result.status = TestStatus.PASSED
                except Exception as identifier:
                    self._log.error("failed", exc_info=identifier)
                    case_result.status = TestStatus.FAILED
                    case_result.errorMessage = str(identifier)
                case_result.elapsed = timer.elapsed()
                self._log.debug(f"method end with {timer}")
            else:
                case_result.status = TestStatus.SKIPPED
                case_result.errorMessage = "skipped as before_case failed"

            timer = create_timer()
            try:
                self.after_case()
            except Exception as identifier:
                self._log.error("after_case failed", exc_info=identifier)
            self._log.debug(f"after_case end with {timer}")

            case_result.elapsed = total_timer.elapsed()
            self._log.info(
                f"result: {case_result.status.name}, " f"elapsed: {total_timer}"
            )
            if self._should_stop:
                self._log.info("received stop message, stop run")
                self.set_status(ActionStatus.STOPPED)
                break

        self._log = suite_log
        timer = create_timer()
        self.after_suite()
        self._log.debug(f"after_suite end with {timer}")

    async def stop(self) -> None:
        self.set_status(ActionStatus.STOPPING)
        self._should_stop = True

    async def close(self) -> None:
        pass


def get_suites() -> Dict[str, TestSuiteData]:
    return _suites


def get_cases() -> Dict[str, TestCaseData]:
    return _cases


def _add_test_class(
    test_class: Type[TestSuite],
    area: Optional[str],
    category: Optional[str],
    description: str,
    tags: List[str],
    name: Optional[str],
) -> None:
    if name is not None:
        name = name
    else:
        name = test_class.__name__
    key = name.lower()
    test_suite = _suites.get(key)
    if test_suite is None:
        test_suite = TestSuiteData(test_class, area, category, description, tags)
        _suites[key] = test_suite
    else:
        raise LisaException(f"duplicate test class name: {key}")

    class_prefix = f"{key}."
    for test_case in _cases.values():
        if test_case.full_name.startswith(class_prefix):
            _add_case_to_suite(test_suite, test_case)
    log = get_logger("init", "test")
    log.info(
        f"registered test suite '{test_suite.key}' "
        f"with test cases: '{', '.join([key for key in test_suite.cases])}'"
    )


def _add_test_method(
    test_method: Callable[[], None], description: str, priority: Optional[int]
) -> None:
    test_case = TestCaseData(test_method, description, priority)
    full_name = test_case.full_name

    if _cases.get(full_name) is None:
        _cases[full_name] = test_case
    else:
        raise LisaException(f"duplicate test class name: {full_name}")

    # this should be None in current observation.
    # the methods are loadded prior to test class
    # in case logic is changed, so keep this logic
    #   to make two collection consistent.
    class_name = full_name.split(".")[0]
    test_suite = _suites.get(class_name)
    if test_suite is not None:
        log = get_logger("init", "test")
        log.debug(f"add case '{test_case.name}' to suite '{test_suite.name}'")
        _add_case_to_suite(test_suite, test_case)


def _add_case_to_suite(test_suite: TestSuiteData, test_case: TestCaseData) -> None:
    test_suite.add_case(test_case)
    test_case.suite = test_suite
