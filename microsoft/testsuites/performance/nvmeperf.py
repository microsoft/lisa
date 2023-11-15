# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from assertpy import assert_that

from lisa import (
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.features import Nvme, NvmeSettings
from lisa.messages import DiskSetupType, DiskType
from lisa.testsuite import TestResult
from lisa.tools import Echo, Lscpu
from microsoft.testsuites.performance.common import perf_disk


@TestSuiteMetadata(
    area="nvme",
    category="performance",
    description="""
    This test suite is to validate NVMe disk performance of Linux VM using fio tool.
    """,
)
class NvmePerformace(TestSuite):
    TIME_OUT = 5000

    @TestCaseMetadata(
        description="""
        This test case uses fio to test NVMe disk performance.
        """,
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            supported_features=[NvmeSettings(disk_count=8)],
        ),
    )
    def perf_nvme(self, node: Node, result: TestResult) -> None:
        nvme = node.features[Nvme]
        nvme_namespaces = nvme.get_raw_nvme_disks()
        disk_count = len(nvme_namespaces)
        assert_that(disk_count).described_as(
            "At least 1 NVMe disk for fio testing."
        ).is_greater_than(0)
        filename = ":".join(nvme_namespaces)
        echo = node.tools[Echo]
        # This will have kernel avoid sending IPI to finish I/O on the issuing CPUs
        # if they are not on the same NUMA node of completion CPU.
        # This setting will give a better and more stable IOPS.
        for nvme_namespace in nvme_namespaces:
            # /dev/nvme0n1 => nvme0n1
            disk_name = nvme_namespace.split("/")[-1]
            echo.write_to_file(
                "0",
                node.get_pure_path(f"/sys/block/{disk_name}/queue/rq_affinity"),
                sudo=True,
            )
        cpu = node.tools[Lscpu]
        core_count = cpu.get_core_count()
        start_iodepth = 1
        max_iodepth = 256
        perf_disk(
            node,
            start_iodepth,
            max_iodepth,
            filename,
            core_count=core_count,
            disk_count=disk_count,
            numjob=core_count,
            disk_setup_type=DiskSetupType.raw,
            disk_type=DiskType.nvme,
            test_result=result,
        )
