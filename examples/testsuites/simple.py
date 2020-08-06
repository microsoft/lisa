from lisa import CaseMetadata, SuiteMetadata
from lisa.common.logger import log
from lisa.core.testSuite import TestSuite


@SuiteMetadata(area="demo", category="simple", tags=["demo"])
class SimpleTestSuite(TestSuite):
    @CaseMetadata(priority=1)
    def hello(self) -> None:
        log.info("hello world")

    @CaseMetadata(priority=1)
    def bye(self) -> None:
        log.info("bye!")

    def caseSetup(self) -> None:
        log.info("setup my test suite")
        log.info("see my code at %s", __file__)

    def caseCleanup(self) -> None:
        log.info("clean up my test suite")

    def beforeCase(self) -> None:
        log.info("before test case")

    def afterCase(self) -> None:
        log.info("after test case")
