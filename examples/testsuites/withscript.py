from pathlib import Path

from lisa import TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.executable import CustomScript, CustomScriptBuilder
from lisa.operating_system import Windows
from lisa.testsuite import simple_requirement


@TestSuiteMetadata(
    area="demo",
    category="simple",
    description="""
    This test suite run a script on linux
    """,
    tags=["demo"],
)
class WithScript(TestSuite):
    def before_suite(self) -> None:
        self._echo_script = CustomScriptBuilder(
            Path(__file__).parent.joinpath("scripts"), ["echo.sh"]
        )

    @TestCaseMetadata(
        description="""
        this test case run script on test node.
        """,
        priority=1,
        requirement=simple_requirement(unsupported_os=[Windows]),
    )
    def script(self) -> None:
        node = self.environment.default_node
        script: CustomScript = node.tools[self._echo_script]
        result = script.run()
        self.log.info(f"result1 stdout: {result}")
        # the second time should be faster, without uploading
        result = script.run()
        self.log.info(f"result2 stdout: {result}")
