# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
from typing import Any, Dict, Optional

from microsoft.testsuites.kselftest.kselftest import Kselftest

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.testsuite import TestResult, simple_requirement
from lisa.tools import Cat
from lisa.util import LisaException, SkippedException, UnsupportedDistroException

# Kselftest subsystems that are known to be incompatible with FIPS mode.
# These are typically tests that validate cryptographic algorithms (MD5, SHA-1, etc.)
# that are disabled/forbidden in FIPS mode.
_FIPS_INCOMPATIBLE_TESTS = [
    "crypto:*",  # Cryptographic algorithm tests - MD5, SHA-1 forbidden in FIPS
    # Other potentially problematic tests can be added here as discovered
]


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

    def __init__(self, metadata: TestSuiteMetadata) -> None:
        super().__init__(metadata)
        # Cache the FIPS check result for this case (a fresh TestSuite
        # instance is created per case, each bound to a single node), so
        # before_case() and verify_kselftest() don't redo the remote check.
        self._fips_enabled_cache: Optional[bool] = None

    def _is_fips_enabled(self, node: Node) -> bool:
        if self._fips_enabled_cache is None:
            fips_result = node.tools[Cat].run(
                "/proc/sys/crypto/fips_enabled",
                force_run=True,
                no_error_log=True,
            )
            self._fips_enabled_cache = (
                fips_result.exit_code == 0 and (fips_result.stdout or "").strip() == "1"
            )
        return self._fips_enabled_cache

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        """
        Pre-test setup hook. Adjusts test configuration for FIPS-enabled kernels.

        On FIPS-enabled kernels, certain kselftest subsystems (particularly crypto
        tests) are incompatible because they test algorithms that FIPS forbids
        (MD5, SHA-1, etc.). Rather than skip the entire suite, we automatically
        add FIPS-incompatible tests to the skip list to maintain coverage of
        compatible subsystems (BPF, networking, timers, etc.).
        """
        node = kwargs["node"]

        if self._is_fips_enabled(node):
            log.info(
                "FIPS mode is enabled. Some kselftest subsystems will be skipped "
                "due to incompatibility with FIPS-restricted algorithms."
            )
            # Note: The actual skip list is applied in verify_kselftest() via
            # the kselftest_skip_tests variable. This log serves as notification
            # that automatic FIPS adjustments are being applied.

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
        - `kselftest_skip_tests_file`: Path to a file listing tests to skip, one
        per line. Merged with `kselftest_skip_tests`. Useful when the skip list is
        long enough to risk command-line length limits.
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
        log: Logger,
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

        # Automatically add FIPS-incompatible tests to the skip list.
        if self._is_fips_enabled(node):
            log.info(
                "FIPS mode enabled: automatically skipping FIPS-incompatible tests "
                f"({', '.join(_FIPS_INCOMPATIBLE_TESTS)})"
            )
            skip_tests_list.extend(_FIPS_INCOMPATIBLE_TESTS)

        # Optionally extend the skip list from a file (one test per line). This
        # keeps the LISA command line short when the skip list is large.
        skip_tests_file = variables.get("kselftest_skip_tests_file", "")
        if skip_tests_file:
            if not os.path.exists(skip_tests_file):
                raise LisaException(
                    f"kselftest_skip_tests_file does not exist: {skip_tests_file}"
                )
            with open(skip_tests_file, "r", encoding="utf-8") as f:
                skip_tests_list.extend(line.strip() for line in f if line.strip())
        # Normalize whitespace and drop empty entries in the combined skip list.
        skip_tests_list = [t.strip() for t in skip_tests_list if t and t.strip()]
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
