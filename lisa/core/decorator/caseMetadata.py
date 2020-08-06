from timeit import default_timer as timer
from typing import Callable, Optional

from lisa.common.logger import log
from lisa.core.test_factory import test_factory


class CaseMetadata(object):
    def __init__(self, priority: Optional[int]) -> None:
        self.priority = priority

    def __call__(self, func: Callable[..., None]) -> Callable[..., None]:
        test_factory.addTestMethod(func, self.priority)

        def wrapper(*args: object) -> None:
            log.info("case '%s' started", func.__name__)
            start = timer()
            func(*args)
            end = timer()
            log.info("case '%s' ended with %f", func.__name__, end - start)

        return wrapper
