from lisa import SuiteMetadata, CaseMetadata
from lisa.common.logger import log
from lisa.core.testSuite import TestSuite


@SuiteMetadata(area="demo", category="simple", tags=["demo"])
class SimpleTestSuite(TestSuite):
    @CaseMetadata(priority=1)
    def hello(self):
        log.info("hello world")

    @CaseMetadata(priority=1)
    def bye(self):
        log.info("bye!")

    def caseSetup(self):
        log.info("setup my test suite")
        log.info("see my code at %s", __file__)

    def caseCleanup(self):
        log.info("clean up my test suite")

    def beforeCase(self):
        log.info("before test case")

    def afterCase(self):
        log.info("after test case")
