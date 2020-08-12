from pathlib import Path

from lisa import TestCaseMetadata, TestSuiteMetadata
from lisa.core.customScript import CustomScript, CustomScriptBuilder
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
    def beforeSuite(self) -> None:
        self.echoScript = CustomScriptBuilder(
            Path(__file__).parent.joinpath("scripts"), ["echo.sh"]
        )

    @TestCaseMetadata(
        description="""
        this test case run script on test node.
        """,
        priority=1,
    )
    def script(self) -> None:
        node = self.environment.defaultNode
        script: CustomScript = node.getTool(self.echoScript)
        result = script.run()
        log.info(f"result stdout: {result.stdout}")
