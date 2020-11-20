from pathlib import Path

import asserts

from lisa import TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.executable import CustomScript, CustomScriptBuilder
from lisa.operating_system import Windows
from lisa.testsuite import simple_requirement
from lisa.util.perf_timer import create_timer


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
        this test case run script on a linux node, and demostrate
        1. how to use customized script on tested node.
        1. how to use requirement to limit case excludes an os.
        2. use perf_timer to measure performance and output result.
        """,
        priority=1,
        requirement=simple_requirement(unsupported_os=[Windows]),
    )
    def script(self) -> None:
        node = self.environment.default_node
        timer1 = create_timer()
        script: CustomScript = node.tools[self._echo_script]
        result1 = script.run()
        self.log.info(f"first run finished within {timer1}")
        timer2 = create_timer()
        result2 = script.run()
        asserts.assert_equal(result1.stdout, result2.stdout)
        if node.is_remote:
            # the timer will be significant different on a remote node.
            asserts.assert_greater(
                timer1.elapsed(),
                timer2.elapsed(),
                "the second time should be faster, without uploading",
            )
        self.log.info(
            f"second run finished within {timer2}, total: {timer1.elapsed_text(False)}"
        )
