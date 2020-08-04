from lisa.core.testfactory import testFactory
from typing import List


class SuiteMetadata:
    def __init__(self, area: str, category: str, tags: List[str], name=None):
        self.area = area
        self.category = category
        self.tags = tags
        self.name = name

    def __call__(self, test_class):
        testFactory.addTestClass(
            test_class, self.area, self.category, self.tags, self.name
        )

        def wrapper(test_class, *args):
            return test_class(args)

        return wrapper
