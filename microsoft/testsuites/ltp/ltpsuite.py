# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from logging import Logger
from typing import Any, Dict

from lisa import (
    Environment,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
    simple_requirement,
)
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
    _TIME_OUT = 12000
    LTP_LITE_TESTS = ["math", "fsx", "ipc", "mm", "sched", "pty", "fs"]
    LTP_REQUIRED_DISK_SIZE_IN_GB = 2

    @TestCaseMetadata(
        description="""
        This test case will run Ltp lite tests.
        """,
        priority=3,
        timeout=_TIME_OUT,
        requirement=simple_requirement(
            min_core_count=8,
            disk=schema.DiskOptionSettings(
                data_disk_count=search_space.IntRange(min=1),
                data_disk_size=search_space.IntRange(min=12),
            ),
        ),
    )
    def ltp_lite(
        self,
        node: Node,
        environment: Environment,
        log_path: str,
        variables: Dict[str, Any],
        result: TestResult,
    ) -> None:
        # parse variables
        tests = variables.get("ltp_test", "")
        skip_tests = variables.get("ltp_skip_test", "")

        # get comma seperated list of tests
        if tests:
            test_list = tests.split(",")
        else:
            test_list = self.LTP_LITE_TESTS

        # get comma seperated list of tests to skip
        if skip_tests:
            skip_test_list = skip_tests.split(",")
        else:
            skip_test_list = []

        # get drive name for running ltp tests
        mountpoint = node.find_partition_with_freespace(
            self.LTP_REQUIRED_DISK_SIZE_IN_GB
        )
        drive_name = node.tools[Lsblk].find_disk_by_mountpoint(mountpoint).device_name

        # run ltp lite tests
        node.tools[Ltp].run_test(
            result,
            environment,
            test_list,
            skip_test_list,
            log_path,
            drive_name=drive_name,
        )

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        # remove swap file created by ltp run since
        # can interfere with other tests
        node: Node = kwargs.pop("node")
        node.tools[Swap].delete_swap()
