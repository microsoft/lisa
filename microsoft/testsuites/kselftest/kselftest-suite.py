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
    # https://github.com/rcghpge/linux-kernel/tree/master/tools/testing/selftests
    _KSELF_LITE_TESTS = ["breakpoints", "cgroup", "core", "coredump"]

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
        try:
            kselftest: Kselftest = node.tools.get(
                Kselftest,
                kselftest_file_path=file_path,
            )
            kselftest.run_all(result, log_path, self._KSELF_TIMEOUT)
        except UnsupportedDistroException as identifier:
            raise SkippedException(identifier)

    @TestCaseMetadata(
        description="""
        This test case will run kself lite tests - a subset of kselftests.
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
        timeout=_CASE_TIME_OUT,
        requirement=simple_requirement(
            min_core_count=16,
        ),
    )
    def verify_kself_lite(
        self,
        node: Node,
        log_path: str,
        variables: Dict[str, Any],
        result: TestResult,
    ) -> None:
        file_path = variables.get("kselftest_file_path", "")
        skip_tests = variables.get("kself_skip_tests", "")
        test_collection = variables.get("kself_test_collection", "")
        # get comma separated list of tests
        if test_collection:
            test_collection_list = test_collection.split(",")
        else:
            test_collection_list = self._KSELF_LITE_TESTS
        try:
            kselftest: Kselftest = node.tools.get(
                Kselftest,
                kselftest_file_path=file_path,
            )
            kselftest.run_all(test_result=result, log_path=log_path, timeout=self._KSELF_TIMEOUT, run_collections=test_collection_list, skip_tests=skip_tests)
        except UnsupportedDistroException as identifier:
            raise SkippedException(identifier)