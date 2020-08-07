from lisa import CaseMetadata, SuiteMetadata
from lisa.core.testSuite import TestSuite
from lisa.util.logger import log


@SuiteMetadata(
    area="demo",
    category="simple",
    description="""
    this is an example test suite.
    it helps to understand how to write a test case.
    """,
    tags=["demo"],
)
class HelloWorld(TestSuite):
    @CaseMetadata(
        description="""
        this test case use default node to start a procecss to echo hello world.
        """,
        priority=1,
    )
    def hello(self) -> None:
        log.info(f"node count: {len(self.environment.nodes)}")
        default_node = self.environment.defaultNode
        result = default_node.execute("echo hello world!")
        log.info(f"stdout of node: '{result.stdout}'")
        log.info(f"stderr of node: '{result.stderr}'")
        log.info(f"exitCode of node: '{result.exitCode}'")
        log.info("try me on a remote node, same code!")

    @CaseMetadata(
        description="""
        do nothing, show how caseSetup, suiteSetup works.
        """,
        priority=2,
    )
    def bye(self) -> None:
        log.info("bye!")

    def beforeSuite(self) -> None:
        log.info("setup my test suite")
        log.info(f"see my code at {__file__}")

    def afterSuite(self) -> None:
        log.info("clean up my test suite")

    def beforeCase(self) -> None:
        log.info("before test case")

    def afterCase(self) -> None:
        log.info("after test case")
