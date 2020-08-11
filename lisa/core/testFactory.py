from typing import Callable, Dict, List, Optional, Type

from singleton_decorator import singleton  # type: ignore

from lisa.core.testSuite import TestSuite
from lisa.util.logger import log


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
        self.key: str = self.name.lower()
        self.full_name = method.__qualname__.lower()
        self.method = method
        self.description = description
        self.priority = priority
        self.suite: TestSuiteData


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

    def addCase(self, test_case: TestCaseData) -> None:
        if self.cases.get(test_case.key) is None:
            self.cases[test_case.key] = test_case
        else:
            raise Exception(f"TestSuiteData has test method {test_case.key} already")


@singleton
class TestFactory:
    def __init__(self) -> None:
        self.suites: Dict[str, TestSuiteData] = dict()
        self.cases: Dict[str, TestCaseData] = dict()

    def addTestClass(
        self,
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
        test_suite = self.suites.get(key)
        if test_suite is None:
            test_suite = TestSuiteData(test_class, area, category, description, tags)
            self.suites[key] = test_suite
        else:
            raise Exception(f"TestFactory duplicate test class name: {key}")

        class_prefix = f"{key}."
        for test_case in self.cases.values():
            if test_case.full_name.startswith(class_prefix):
                self._addCaseToSuite(test_suite, test_case)
        log.info(
            f"registered test suite '{test_suite.key}' "
            f"with test cases: '{', '.join([key for key in test_suite.cases])}'"
        )

    def addTestMethod(
        self, test_method: Callable[[], None], description: str, priority: Optional[int]
    ) -> None:
        test_case = TestCaseData(test_method, description, priority)
        full_name = test_case.full_name

        if self.cases.get(full_name) is None:
            self.cases[full_name] = test_case
        else:
            raise Exception(f"duplicate test class name: {full_name}")

        # this should be None in current observation.
        # the methods are loadded prior to test class
        # in case logic is changed, so keep this logic
        #   to make two collection consistent.
        class_name = full_name.split(".")[0]
        test_suite = self.suites.get(class_name)
        if test_suite is not None:
            log.debug(f"add case '{test_case.name}' to suite '{test_suite.name}'")
            self._addCaseToSuite(test_suite, test_case)

    def _addCaseToSuite(
        self, test_suite: TestSuiteData, test_case: TestCaseData
    ) -> None:
        test_suite.addCase(test_case)
        test_case.suite = test_suite
