from __future__ import annotations

import unittest
from abc import ABCMeta
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Type

from lisa.action import Action, ActionStatus
from lisa.util.exceptions import LisaException
from lisa.util.logger import get_logger
from lisa.util.perf_timer import create_timer

if TYPE_CHECKING:
    from lisa.environment import Environment


TestStatus = Enum("TestStatus", ["NOTRUN", "RUNNING", "FAILED", "PASSED", "SKIPPED"])

_suites: Dict[str, TestSuiteMetadata] = dict()
_cases: Dict[str, TestCaseMetadata] = dict()


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
        name: str = "",
    ) -> None:
        self.name = name
        self.cases: List[TestCaseMetadata] = []

        self.area = area
        self.category = category
        if tags:
            self.tags = tags
        else:
            self.tags = []
        self.description = description

    def __call__(self, test_class: Type[TestSuite]) -> Callable[..., object]:
        self.test_class = test_class
        if not self.name:
            self.name = test_class.__name__
        _add_suite_metadata(self)

        @wraps(self.test_class)
        def wrapper(
            test_class: Type[TestSuite],
            environment: Environment,
            cases: List[TestResult],
            metadata: TestSuiteMetadata,
        ) -> TestSuite:
            return test_class(environment, cases, metadata)

        return wrapper


class TestCaseMetadata:
    def __init__(self, description: str, priority: int = 2) -> None:
        self.priority = priority
        self.description = description

    def __getattr__(self, key: str) -> Any:
        # inherit any attributes of metadata
        assert self.suite, "suite is not set before use metadata"
        return getattr(self.suite, key)

    def __call__(self, func: Callable[..., None]) -> Callable[..., None]:
        self.name = func.__name__
        self.full_name = func.__qualname__

        self._func = func
        _add_case_metadata(self)

        @wraps(self._func)
        def wrapper(*args: object) -> None:
            func(*args)

        return wrapper

    def set_suite(self, suite: TestSuiteMetadata) -> None:
        self.suite: TestSuiteMetadata = suite


class TestCaseData:
    def __init__(self, metadata: TestCaseMetadata):
        self.metadata = metadata

        # all runtime setting fields
        self.select_action: str = ""
        self.times: int = 1
        self.retry: int = 0
        self.use_new_environmnet: bool = False
        self.ignore_failure: bool = False
        self.environment_name: str = ""

    def __getattr__(self, key: str) -> Any:
        # inherit any attributes of metadata
        assert self.metadata
        return getattr(self.metadata, key)


class TestSuite(Action, unittest.TestCase, metaclass=ABCMeta):
    def __init__(
        self,
        environment: Environment,
        case_results: List[TestResult],
        metadata: TestSuiteMetadata,
    ) -> None:
        self.environment = environment
        # test cases to run, must be a test method in this class.
        self.case_results = case_results
        self._metadata = metadata
        self._should_stop = False
        self._log = get_logger("suite", metadata.name)

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
            self._log = get_logger("case", f"{case_result.case.full_name}")

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


def get_suites_metadata() -> Dict[str, TestSuiteMetadata]:
    return _suites


def get_cases_metadata() -> Dict[str, TestCaseMetadata]:
    return _cases


def _add_suite_metadata(metadata: TestSuiteMetadata) -> None:
    if metadata.name:
        key = metadata.name
    else:
        key = metadata.test_class.__name__
    exist_metadata = _suites.get(key)
    if exist_metadata is None:
        _suites[key] = metadata
    else:
        raise LisaException(f"duplicate test class name: {key}")

    class_prefix = f"{key}."
    for test_case in _cases.values():
        if test_case.full_name.startswith(class_prefix):
            _add_case_to_suite(metadata, test_case)
    log = get_logger("init", "test")
    log.info(
        f"registered test suite '{key}' "
        f"with test cases: '{', '.join([case.name for case in metadata.cases])}'"
    )


def _add_case_metadata(metadata: TestCaseMetadata) -> None:

    full_name = metadata.full_name
    if _cases.get(full_name) is None:
        _cases[full_name] = metadata
    else:
        raise LisaException(f"duplicate test class name: {full_name}")

    # this should be None in current observation.
    # the methods are loadded prior to test class
    # in case logic is changed, so keep this logic
    #   to make two collection consistent.
    class_name = full_name.split(".")[0]
    test_suite = _suites.get(class_name)
    if test_suite:
        log = get_logger("init", "test")
        log.debug(f"add case '{metadata.name}' to suite '{test_suite.name}'")
        _add_case_to_suite(test_suite, metadata)


def _add_case_to_suite(
    test_suite: TestSuiteMetadata, test_case: TestCaseMetadata
) -> None:
    test_case.suite = test_suite
    test_suite.cases.append(test_case)
