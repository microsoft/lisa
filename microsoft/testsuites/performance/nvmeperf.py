# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from lisa import (
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.features import Nvme, NvmeSettings
from lisa.testsuite import TestResult
from lisa.tools.fio import IoEngine
from microsoft.testsuites.performance.common import perf_nvme


@TestSuiteMetadata(
    area="nvme",
    category="performance",
    description="""
    This test suite is to validate NVMe disk performance of Linux VM using fio tool.
    """,
)
class NvmePerformace(TestSuite):
    TIME_OUT = 7200

    @TestCaseMetadata(
        description="""
        This test case uses fio to test NVMe disk performance
        using 'libaio' as ioengine
        """,
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            supported_features=[NvmeSettings(disk_count=8)],
        ),
    )
    def perf_nvme(self, node: Node, result: TestResult) -> None:
        perf_nvme(node, result)

    @TestCaseMetadata(
        description="""
        This test case uses fio to test NVMe disk performance
        using 'io_uring' as ioengine.
        """,
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def perf_nvme_io_uring(self, node: Node, result: TestResult) -> None:
        perf_nvme(node, ioengine=IoEngine.IO_URING, result=result, max_iodepth=1024)
