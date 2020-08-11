from pathlib import Path

from lisa import TestCaseMetadata, TestSuiteMetadata
from lisa.core.customScript import CustomScriptSpec
from lisa.core.testSuite import TestSuite
from lisa.util.logger import log


@TestSuiteMetadata(
    area="demo",
    category="simple",
    description="""
    This test suite run a script
    """,
    tags=["demo"],
)
class WithScript(TestSuite):
    @property
    def skipRun(self) -> bool:
        node = self.environment.defaultNode
        return not node.isLinux

    def beforeSuite(self) -> None:
        self.echoScript = CustomScriptSpec(Path(__file__).parent, ["scripts/echo.sh"])

    @TestCaseMetadata(
        description="""
        this test case run script on test node.
        """,
        priority=1,
    )
    def script(self) -> None:
        node = self.environment.defaultNode
        script_instance = node.getScript(self.echoScript)
        result = script_instance.run()
        log.info(f"result stdout: {result.stdout}")
