from typing import Any, Dict

from lisa import Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.testsuite import TestResult, simple_requirement
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
    # kselftests take about a one and half an hour to complete,
    # timeout below is in seconds and set to 2 hours.
    _CASE_TIME_OUT = 7200
    _KSELF_TIMEOUT = 6700

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

        Customization:
        Users can customize the test by specifying the
        `kselftest_include_test_collections` and `kselftest_skip_tests` variables
        in the runbook. For example:
        - `kselftest_include_test_collections`: A comma-separated list of collections
        to run (e.g., "bpf,net,timers").
        - `kselftest_skip_tests`: A comma-separated list of tests to skip
        (e.g., "net:test_tcp,test_udp").
        """,
        priority=3,
        timeout=_CASE_TIME_OUT,
        requirement=simple_requirement(
            min_core_count=16,
        ),
    )
    def verify_kselftest(
        self,
        node: Node,
        log_path: str,
        variables: Dict[str, Any],
        result: TestResult,
    ) -> None:
        file_path = variables.get("kselftest_file_path", "")
        working_path = variables.get("kselftest_working_path", "")
        run_as_root = variables.get("kselftest_run_as_root", False)
        test_collection_list = (
            variables.get("kselftest_include_test_collections", "").split(",")
            if variables.get("kselftest_include_test_collections", "")
            else []
        )
        skip_tests_list = (
            variables.get("kselftest_skip_tests", "").split(",")
            if variables.get("kselftest_skip_tests", "")
            else []
        )

        try:
            kselftest: Kselftest = node.tools.get(
                Kselftest,
                working_path=working_path,
                file_path=file_path,
            )
            kselftest.run_all(
                test_result=result,
                log_path=log_path,
                timeout=self._KSELF_TIMEOUT,
                run_test_as_root=run_as_root,
                run_collections=test_collection_list,
                skip_tests=skip_tests_list,
            )
        except UnsupportedDistroException as e:
            raise SkippedException(e)
