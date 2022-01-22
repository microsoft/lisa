# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import List

from assertpy import assert_that

from lisa import (
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.environment import Environment
from lisa.features import Nvme, NvmeSettings
from lisa.messages import DiskPerformanceMessage, DiskSetupType, DiskType
from lisa.tools import Echo, Lscpu
from microsoft.testsuites.performance.common import (
    handle_and_send_back_results,
    run_perf_test,
)


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
    def perf_nvme(self, node: Node, environment: Environment) -> None:
        nvme = node.features[Nvme]
        nvme_namespaces = nvme.get_namespaces()
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
        fio_messages: List[DiskPerformanceMessage] = run_perf_test(
            node, start_iodepth, max_iodepth, filename, numjob=core_count
        )
        handle_and_send_back_results(
            core_count,
            disk_count,
            environment,
            DiskSetupType.raw,
            DiskType.nvme,
            "perf_nvme",
            fio_messages,
        )
