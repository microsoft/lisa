from lisa import CaseMetadata, SuiteMetadata
from lisa.core.testSuite import TestSuite
from lisa.util.logger import log


@SuiteMetadata(area="demo", category="simple", tags=["demo"])
class SimpleTestSuite(TestSuite):
    @CaseMetadata(priority=1)
    def hello(self) -> None:
        log.info("environment: %s", len(self.environment.nodes))
        default_node = self.environment.defaultNode
        result = default_node.execute("echo hello world!")
        log.info("stdout of node: '%s'", result.stdout)
        log.info("stderr of node: '%s'", result.stderr)
        log.info("exitCode of node: '%s'", result.exitCode)
        log.info("try me on a remote node, same code!")

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
