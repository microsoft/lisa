from lisa import TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.tools import Echo, Uname


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
        self._log.info(f"node count: {len(self.environment.nodes)}")
        node = self.environment.default_node

        uname = node.tools[Uname]
        info = uname.get_linux_information()
        self._log.info(
            f"release: '{info.kernel_release}', version: '{info.kernel_version}', "
            f"hardware: '{info.hardware_platform}', os: '{info.operating_system}'"
        )

        # get process output directly.
        echo = node.tools[Echo]
        result = echo.run("hello world!")
        self._log.info(f"stdout of node: '{result.stdout}'")
        self._log.info(f"stderr of node: '{result.stderr}'")
        self._log.info(f"exitCode of node: '{result.exit_code}'")

    @TestCaseMetadata(
        description="""
        demonstrate a simple way to run command in one line.
        """,
        priority=2,
    )
    def bye(self) -> None:
        node = self.environment.default_node
        # use it once like this way before use short cut
        node.tools[Echo]
        self._log.info(f"stdout of node: '{node.tools.echo('bye!')}'")

    def before_suite(self) -> None:
        self._log.info("setup my test suite")
        self._log.info(f"see my code at {__file__}")

    def after_suite(self) -> None:
        self._log.info("clean up my test suite")

    def before_case(self) -> None:
        self._log.info("before test case")

    def after_case(self) -> None:
        self._log.info("after test case")
