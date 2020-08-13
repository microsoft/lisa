from lisa import TestCaseMetadata, TestSuiteMetadata
from lisa.core.testSuite import TestSuite
from lisa.tool import Echo, Uname
from lisa.util.logger import log


@TestSuiteMetadata(
    area="demo",
    category="simple",
    description="""
    this is an example test suite.
    it helps to understand how to write a test case.
    """,
    tags=["demo"],
)
class HelloWorld(TestSuite):
    @TestCaseMetadata(
        description="""
        this test case use default node to
            1. get system info
            2. echo hello world!
        """,
        priority=1,
    )
    def hello(self) -> None:
        log.info(f"node count: {len(self.environment.nodes)}")
        node = self.environment.default_node

        uname = node.get_tool(Uname)
        release, version, hardware, os = uname.get_linux_information()
        log.info(
            f"release: '{release}', version: '{version}', "
            f"hardware: '{hardware}', os: '{os}'"
        )

        # get process output directly.
        echo = node.get_tool(Echo)
        result = echo.run("hello world!")
        log.info(f"stdout of node: '{result.stdout}'")
        log.info(f"stderr of node: '{result.stderr}'")
        log.info(f"exitCode of node: '{result.exit_code}'")

    @TestCaseMetadata(
        description="""
        do nothing, show how caseSetup, suiteSetup works.
        """,
        priority=2,
    )
    def bye(self) -> None:
        log.info("bye!")

    def before_suite(self) -> None:
        log.info("setup my test suite")
        log.info(f"see my code at {__file__}")

    def after_suite(self) -> None:
        log.info("clean up my test suite")

    def before_case(self) -> None:
        log.info("before test case")

    def after_case(self) -> None:
        log.info("after test case")
