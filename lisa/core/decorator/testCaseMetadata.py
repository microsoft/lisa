from timeit import default_timer as timer
from typing import Callable, Optional

from lisa.core.testFactory import TestFactory
from lisa.util.logger import log


class TestCaseMetadata:
    def __init__(self, description: str, priority: Optional[int]) -> None:
        self.priority = priority
        self.description = description

    def __call__(self, func: Callable[..., None]) -> Callable[..., None]:
        factory = TestFactory()
        factory.addTestMethod(func, self.description, self.priority)

        def wrapper(*args: object) -> None:
            log.info(f"case '{func.__name__}' started")
            start = timer()
            func(*args)
            end = timer()
            log.info(f"case '{func.__name__}' ended with {end - start:.3f} sec")

        return wrapper
