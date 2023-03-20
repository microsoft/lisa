# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from typing import Any

from assertpy import assert_that

from lisa import (
    CustomScript,
    CustomScriptBuilder,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    create_timer,
)


@TestSuiteMetadata(
    area="demo",
    category="functional",
    description="""
    This test suite run a script on linux
    """,
)
class WithScript(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        self._echo_script = CustomScriptBuilder(
            Path(__file__).parent.joinpath("scripts"), ["echo.sh"]
        )

    @TestCaseMetadata(
        description="""
        this test case run script on a linux node, and demonstrate
        1. how to use customized script on tested node.
        1. how to use requirement to limit case excludes an os.
        2. use perf_timer to measure performance and output result.
        """,
        priority=1,
    )
    def script(self, node: Node, log: Logger) -> None:
        timer1 = create_timer()
        script: CustomScript = node.tools[self._echo_script]
        result1 = script.run()
        log.info(f"first run finished within {timer1}")
        timer2 = create_timer()
        result2 = script.run(force_run=True)
        assert_that(result1.stdout).is_equal_to(result2.stdout)
        if node.is_remote:
            # the timer will be significant different on a remote node.
            assert_that(
                timer1.elapsed(), "the second time should be faster, without uploading"
            ).is_greater_than(timer2.elapsed())
        log.info(
            f"second run finished within {timer2}, total: {timer1.elapsed_text(False)}"
        )
