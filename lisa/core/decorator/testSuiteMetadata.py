from __future__ import annotations

from typing import TYPE_CHECKING, Callable, List, Optional, Type

from lisa.core.testFactory import TestFactory
from lisa.core.testSuite import TestSuite

if TYPE_CHECKING:
    from lisa.core.environment import Environment
    from lisa.core.testFactory import TestSuiteData


class TestSuiteMetadata:
    def __init__(
        self,
        area: str,
        category: str,
        description: str,
        tags: List[str],
        name: Optional[str] = None,
    ) -> None:
        self.area = area
        self.category = category
        self.tags = tags
        self.description = description
        self.name = name

    def __call__(self, test_class: Type[TestSuite]) -> Callable[..., object]:
        factory = TestFactory()
        factory.addTestClass(
            test_class, self.area, self.category, self.description, self.tags, self.name
        )

        def wrapper(
            test_class: Type[TestSuite],
            environment: Environment,
            cases: List[str],
            metadata: TestSuiteData,
        ) -> TestSuite:
            return test_class(environment, cases, metadata)

        return wrapper
