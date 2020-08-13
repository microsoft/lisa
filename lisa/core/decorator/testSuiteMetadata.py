from __future__ import annotations

from typing import TYPE_CHECKING, Callable, List, Optional, Type

from lisa.core.testFactory import TestFactory
from lisa.core.testSuite import TestSuite

if TYPE_CHECKING:
    from lisa.core.environment import Environment
    from lisa.core.testFactory import TestSuiteData
    from lisa.core.testResult import TestResult


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
        factory = TestFactory()
        factory.add_class(
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
