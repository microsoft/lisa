from lisa.core.decorator.testclass import TestClass
from lisa.core.testsuite import TestSuite
from lisa import TestMethod, log


@TestClass("sample area", "sample category", ["demo"])
class SimpleTestSuite(TestSuite):
    @TestMethod(priority=1)
    def hello(self):
        log.info("hello world")

    @TestMethod(priority=1)
    def bye(self):
        log.info("bye!")

    def setup(self):
        log.info("setup my test suite")

    def cleanup(self):
        log.info("clean up my test suite")

    def beforeCase(self):
        log.info("before test case")

    def afterCase(self):
        log.info("after test case")
