from timeit import default_timer as timer
from lisa import log
from lisa.core.testfactory import testFactory


class CaseMetadata(object):
    def __init__(self, priority):
        self.priority = priority

    def __call__(self, func):
        testFactory.addTestMethod(func, self.priority)

        def wrapper(*args):
            log.info("case '%s' started", func.__name__)
            start = timer()
            func(args)
            end = timer()
            log.info("case '%s' ended with %f", func.__name__, end - start)

        return wrapper
