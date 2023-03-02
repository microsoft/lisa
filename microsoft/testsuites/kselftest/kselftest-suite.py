from typing import Any, Dict

from lisa import Environment, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.testsuite import TestResult
from microsoft.testsuites.kselftest.kselftest import Kselftest


@TestSuiteMetadata(
    area="kselftest",
    category="community",
    description="""
    This test suite is used to run kselftests.
    """,
)
class KselftestTestsuite(TestSuite):
    # kselftests take under an hour to complete, timeout below is in seconds
    _TIME_OUT = 3600

    @TestCaseMetadata(
        description="""
        This test case will run linux kernel self tests.
        Steps:
        1. Provide a tarball of kselftest binaries kselftests.tar.xz in a .yml file.
        Example:
        - name: kselftest_file_path
          value: <path_to_kselftests.tar.xz>
          is_case_visible: true
        2. Verify that the Kselftest tool extracts the tar, runs the script
        run_kselftest.sh and redirects test results to a file kselftest-results.txt.
        """,
        priority=3,
        timeout=_TIME_OUT,
    )
    def verify_kselftest(
        self,
        node: Node,
        environment: Environment,
        log_path: str,
        variables: Dict[str, Any],
        result: TestResult,
    ) -> None:
        kselftest = node.tools.get(
            Kselftest,
            variables["kselftest_file_path"],
        )

        kselftest.run_all(
            result,
            environment,
            log_path,
        )
