from typing import Any, Dict

from lisa import Environment, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.testsuite import TestResult
from lisa.util import SkippedException, UnsupportedDistroException
from microsoft.testsuites.kselftest.kselftest import Kselftest


@TestSuiteMetadata(
    area="kselftest",
    category="community",
    description="""
    This test suite is used to run kselftests.
    """,
)
class KselftestTestsuite(TestSuite):
    # kselftests take about an hour to complete, timeout below
    # is in seconds and set to 1.5x an hour i.e. 90mins
    _TIME_OUT = 5400

    @TestCaseMetadata(
        description="""
        This test case runs linux kernel self tests on Mariner VMs.
        Cases:
        1. When a tarball is specified in .yml file, extract the tar and run kselftests.
        Example:
        - name: kselftest_file_path
          value: <path_to_kselftests.tar.xz>
          is_case_visible: true
        2. When a tarball is not specified in .yml file, clone Mariner kernel,
        copy current config to .config, build kselftests and generate a tar.

        For both cases, verify that the kselftest tool extracts the tar, runs the script
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
        file_path = variables.get("kselftest_file_path", "")
        try:
            kselftest: Kselftest = node.tools.get(
                Kselftest,
                kselftest_file_path=file_path,
            )
            kselftest.run_all(
                result,
                environment,
                log_path,
            )
        except UnsupportedDistroException as identifier:
            raise SkippedException(identifier)
