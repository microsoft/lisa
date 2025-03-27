from typing import Any, Dict, List, Optional

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
    # the default list of tests executed as part of kself lite
    _KSELF_LITE_TESTS = [
        "bpf",
        "core",
        "futex",
        "ipc",
        "kexec",
        "mm",
        "net",
        "timers",
        "x86",
    ]

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
        try:
            self._run_kselftest(
                node,
                log_path,
                variables,
                result,
            )
        except UnsupportedDistroException as identifier:
            raise SkippedException(identifier)

    @TestCaseMetadata(
        description="""
        This test case will run kself lite tests - a subset of kselftests.
        A predefined value is provided in the list _KSELF_LITE_TESTS,
        though a custom value can be passed to the test case as well.
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
        3. For this lite version, the list of collections to run and the list
        of tests to skip can be specified in the .yml file.
        Example:
        - name: kself_skip_tests
          value: <comma_separated_list_of_tests_to_skip - format: collection:test_name>
          is_case_visible: true
        - name: kself_test_collection
          value: <comma_separated_list_of_collections_to_run - format: collection_name>
          is_case_visible: true
        """,
        priority=3,
        timeout=_CASE_TIME_OUT,
        requirement=simple_requirement(
            min_core_count=16,
        ),
    )
    def verify_kselftest_lite(
        self,
        node: Node,
        log_path: str,
        variables: Dict[str, Any],
        result: TestResult,
    ) -> None:
        test_collection_list = variables.get("kself_test_collection", "").split(",") if variables.get("kself_test_collection", "") else self._KSELF_LITE_TESTS
        skip_tests_list = variables.get("kself_skip_tests", "").split(",") if variables.get("kself_skip_tests", "") else []
        try:
            self._run_kselftest(
                node,
                log_path,
                variables,
                result,
                test_collection_list,
                skip_tests_list,
            )
        except UnsupportedDistroException as identifier:
            raise SkippedException(identifier)

    def _run_kselftest(
        self,
        node: Node,
        log_path: str,
        variables: Dict[str, Any],
        result: TestResult,
        run_collections: Optional[List[str]] = None,
        skip_tests: Optional[List[str]] = None,
    ) -> None:
        run_collections = run_collections or []
        skip_tests = skip_tests or []
        kselftest: Kselftest = node.tools.get(
            Kselftest,
            kselftest_file_path=variables.get("kselftest_file_path", ""),
        )
        kselftest.run_all(
            test_result=result,
            log_path=log_path,
            timeout=self._KSELF_TIMEOUT,
            run_collections=run_collections,
            skip_tests=skip_tests,
        )