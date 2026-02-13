# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from logging import Logger
from pathlib import Path
from typing import Any, Dict

from lisa import (
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
    simple_requirement,
)
from lisa.operating_system import BSD, Windows
from lisa.testsuite import TestResult
from lisa.tools import Lsblk, Swap
from microsoft.testsuites.ltp.ltp import Ltp


@TestSuiteMetadata(
    area="ltp",
    category="community",
    description="""
    This test suite is used to run Ltp related tests.
    """,
)
class LtpTestsuite(TestSuite):
    _TIME_OUT = 18000
    LTP_LITE_TESTS = "math,ipc,mm,sched,pty,fs"
    LTP_REQUIRED_DISK_SIZE_IN_GB = 2

    @TestCaseMetadata(
        description="""
        This test case will run Ltp lite tests in following priority sequence:
        1. When ltp_binary_file (prebuilt ltp tar) is specified in .yml, case will
        run ltp directly from extracted ltp_binary_file without any configuration.
        2. When ltp_source_file (downloaded ltp code) is specified in .yml,
        case will use it to extract the tar and run ltp, instead of downloading runtime.
        Example:
        - name: ltp_source_file
          value: <path_to_ltp.tar.xz>
          is_case_visible: true
        3. When ltp_binary_file/ltp_source_file not in .yml, clone github with
            ltp_tests_git_tag
        """,
        priority=3,
        timeout=_TIME_OUT,
        requirement=simple_requirement(
            min_core_count=8,
            disk=schema.DiskOptionSettings(
                data_disk_count=search_space.IntRange(min=1),
                data_disk_size=search_space.IntRange(min=12),
            ),
            unsupported_os=[BSD, Windows],
        ),
    )
    def verify_ltp_lite(
        self,
        node: Node,
        log_path: str,
        variables: Dict[str, Any],
        result: TestResult,
    ) -> None:
        test_str = variables.get("ltp_test", "")
        if not test_str:
            test_str = self.LTP_LITE_TESTS
        self._verify_ltp(node, variables, test_str, log_path, result)

    @TestCaseMetadata(
        description="""
        This test case will run Ltp Full tests.
        1. When ltp_source_file (downloaded ltp code) is specified in .yml,
        case will use it to extract the tar and run ltp, instead of downloading runtime.
        Example:
        - name: ltp_source_file
          value: <path_to_ltp.tar.xz>
          is_case_visible: true
        2. When ltp_source_file not in .yml, clone github with ltp_tests_git_tag
        """,
        priority=3,
        timeout=25200,
        requirement=simple_requirement(
            min_core_count=8,
            disk=schema.DiskOptionSettings(
                data_disk_count=search_space.IntRange(min=1),
                data_disk_size=search_space.IntRange(min=12),
            ),
            unsupported_os=[BSD, Windows],
        ),
    )
    def verify_ltp_full(
        self,
        node: Node,
        log_path: str,
        variables: Dict[str, Any],
        result: TestResult,
    ) -> None:
        test_str = variables.get("ltp_test", "")
        self._verify_ltp(node, variables, test_str, log_path, result)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        # remove swap file created by ltp run since
        # can interfere with other tests
        node: Node = kwargs.pop("node")
        node.tools[Swap].delete_swap()

    def _verify_ltp(
        self,
        node: Node,
        variables: Dict[str, Any],
        # empty test_list means run ltp full test
        test_str: str,
        log_path: str,
        result: TestResult,
    ) -> None:
        test_list = test_str.split(",") if test_str else []
        skip_test_str = variables.get("ltp_skip_test", "")

        default_skip_file = Path(__file__).parent / "ltp_skip_file.txt"
        skip_test_file = variables.get(
            "ltp_skip_test_file",
            str(default_skip_file) if default_skip_file.exists() else "",
        )
        source_file = variables.get("ltp_source_file", "")
        git_tag = variables.get("ltp_tests_git_tag", "")
        run_timeout = int(variables.get("ltp_run_timeout", 12000))
        binary_file = variables.get("ltp_binary_file", "")
        install_path = variables.get("ltp_install_path", "")
        # block device is required for few ltp tests
        # If not provided, we will find a disk with enough space
        block_device = variables.get("ltp_block_device", None)

        # get comma separated list of tests to skip
        skip_test_list = skip_test_str.split(",") if skip_test_str else []

        if not block_device and not binary_file:
            mountpoint = node.find_partition_with_freespace(
                self.LTP_REQUIRED_DISK_SIZE_IN_GB, use_os_drive=False, raise_error=False
            )
            if mountpoint:
                block_device = (
                    node.tools[Lsblk].find_disk_by_mountpoint(mountpoint).device_name
                )

        if not test_list:
            # empty test_list means full test, require long timeout
            run_timeout = 25200

        ltp: Ltp = node.tools.get(
            Ltp,
            source_file=source_file,
            binary_file=binary_file,
            git_tag=git_tag,
            install_path=install_path,
        )
        ltp.run_test(
            result,
            test_list,
            skip_test_list,
            log_path,
            skip_test_file,
            block_device=block_device,
            ltp_run_timeout=run_timeout,
        )
