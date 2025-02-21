# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from logging import Logger
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
    LTP_LITE_TESTS = ["math", "fsx", "ipc", "mm", "sched", "pty", "fs"]
    LTP_REQUIRED_DISK_SIZE_IN_GB = 2

    @TestCaseMetadata(
        description="""
        This test case will run Ltp lite tests.
        1. When ltp_source_file (downloaded ltp code) is specified in .yml,
        case will use it to extract the tar and run ltp, instead of downloading runtime.
        Example:
        - name: ltp_source_file
          value: <path_to_ltp.tar.xz>
          is_case_visible: true
        2. When ltp_source_file not in .yml, clone github with ltp_tests_git_tag
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
        # parse variables
        tests = variables.get("ltp_test", "")
        skip_tests = variables.get("ltp_skip_test", "")
        ltp_tests_git_tag = variables.get("ltp_tests_git_tag", "")
        ltp_prebuilt_file = variables.get("ltp_prebuilt_file", "")

        # block device is required for few ltp tests
        # If not provided, we will find a disk with enough space
        block_device = variables.get("ltp_block_device", None)

        # get comma separated list of tests
        if tests:
            test_list = tests.split(",")
        else:
            test_list = self.LTP_LITE_TESTS

        # get comma separated list of tests to skip
        if skip_tests:
            skip_test_list = skip_tests.split(",")
        else:
            skip_test_list = []

        if not block_device:
            mountpoint = node.find_partition_with_freespace(
                self.LTP_REQUIRED_DISK_SIZE_IN_GB, use_os_drive=False, raise_error=False
            )
            if mountpoint:
                block_device = (
                    node.tools[Lsblk].find_disk_by_mountpoint(mountpoint).device_name
                )

        # run ltp lite tests
        ltp: Ltp = node.tools.get(
            Ltp,
            prebuilt_file=ltp_prebuilt_file,
            git_tag=ltp_tests_git_tag,
        )
        ltp.run_test(
            result,
            test_list,
            skip_test_list,
            log_path,
            block_device=block_device,
        )

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        # remove swap file created by ltp run since
        # can interfere with other tests
        node: Node = kwargs.pop("node")
        node.tools[Swap].delete_swap()
