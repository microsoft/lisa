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
        This test case will run a lighter version of kselftests, focusing on specific
        test suites and skipping less critical and noisy tests. The default
        list of tests to run is defined in the `_KSELF_LITE_TESTS` list, which includes
        collections such as "bpf", "core", "futex", "ipc", "mm", "net", "timers", and
        "x86". These tests were selected to cover critical kernel functionalities, such
        as networking, timer management, and architecture-specific features, while
        reducing execution time and resource usage.

        Purpose:
        This "lite" version is designed for scenarios where running the full kselftest
        suite is not feasible or not required. It ensures that
        critical kernel features are tested without the overhead of running the entire
        suite. Also, ensuring that the user can avoid tests/
        suites that are known to fail or are not relevant to their use case.

        Customization:
        Users can customize the test by specifying the `kself_test_collection` and
        `kself_skip_tests` variables in the runbook. For example:
        - `kself_test_collection`: A comma-separated list of collections to run
        (e.g., "bpf,net,timers").
        - `kself_skip_tests`: A comma-separated list of tests to skip
        (e.g., "net:test_tcp,test_udp").

        For both cases, the test extracts the tarball (if provided), runs the
        `run_kselftest.sh` script, and redirects the test results to a file named
        `kselftest-results.txt`.

        Default Test Suites:
        The `_KSELF_LITE_TESTS` list includes the following test suites:
        - `bpf`: Tests related to the Berkeley Packet Filter (BPF) subsystem.
        - `core`: Core kernel functionality tests.
        - `futex`: Tests for fast user-space mutexes.
        - `ipc`: Inter-process communication tests.
        - `mm`: Memory management tests.
        - `net`: Networking-related tests, including TCP, UDP, and other network
        protocols.
        - `timers`: Tests for kernel timer functionality and timekeeping.
        - `x86`: Architecture-specific tests for the x86 platform.
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
        test_collection_list = (
            variables.get("kself_test_collection", "").split(",")
            if variables.get("kself_test_collection", "")
            else self._KSELF_LITE_TESTS
        )
        skip_tests_list = (
            variables.get("kself_skip_tests", "").split(",")
            if variables.get("kself_skip_tests", "")
            else []
        )
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
        file_path = variables.get("kselftest_file_path", "")
        working_path = variables.get("kselftest_working_path", "")
        run_as_root = variables.get("kselftest_run_as_root", False)
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
            run_collections=run_collections,
            skip_tests=skip_tests,
        )
