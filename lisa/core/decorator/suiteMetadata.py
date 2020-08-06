from __future__ import annotations

from typing import TYPE_CHECKING, Callable, List, Optional, Type

from lisa.core.test_factory import test_factory
from lisa.core.testSuite import TestSuite

if TYPE_CHECKING:
    from lisa.core.environment import Environment


class SuiteMetadata:
    def __init__(
        self, area: str, category: str, tags: List[str], name: Optional[str] = None
    ) -> None:
        self.area = area
        self.category = category
        self.tags = tags
        self.name = name

    def __call__(self, test_class: Type[TestSuite]) -> Callable[..., object]:
        test_factory.addTestClass(
            test_class, self.area, self.category, self.tags, self.name
        )

        def wrapper(
            test_class: Type[TestSuite], environment: Environment, cases: List[str]
        ) -> TestSuite:
            return test_class(environment, cases)

        return wrapper
