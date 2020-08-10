from lisa import CaseMetadata, SuiteMetadata
from lisa.core.testSuite import TestSuite
from lisa.tool import Echo, Uname
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
        this test case use default node to
            1. get system info
            2. echo hello world!
        """,
        priority=1,
    )
    def hello(self) -> None:
        log.info(f"node count: {len(self.environment.nodes)}")
        node = self.environment.defaultNode

        if node.isRemote:
            log.info("It's remote machine, try on local one!")
        else:
            log.info("It's local machine, try on remote one!")

        if node.isLinux:
            uname = node.getTool(Uname)
            release, version, hardware = uname.getLinuxInformation()
            log.info(
                f"release: '{release}', version: '{version}', hardware: '{hardware}'"
            )
            log.info("It's Linux, try on Windows!")
        else:
            log.info("It's Windows, try on Linux!")

        # get process output directly.
        echo = node.getTool(Echo)
        result = echo.run("hello world!")
        log.info(f"stdout of node: '{result.stdout}'")
        log.info(f"stderr of node: '{result.stderr}'")
        log.info(f"exitCode of node: '{result.exitCode}'")

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
