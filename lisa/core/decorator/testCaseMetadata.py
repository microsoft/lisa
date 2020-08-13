from typing import Callable, Optional

from lisa.core.testFactory import TestFactory


class TestCaseMetadata:
    def __init__(self, description: str, priority: Optional[int]) -> None:
        self._priority = priority
        self._description = description

    def __call__(self, func: Callable[..., None]) -> Callable[..., None]:
        factory = TestFactory()
        factory.add_method(func, self._description, self._priority)

        def wrapper(*args: object) -> None:
            func(*args)

        return wrapper
