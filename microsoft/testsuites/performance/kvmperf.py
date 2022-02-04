# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import inspect
import time
from typing import Any, Dict, List

from lisa import (
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
    simple_requirement,
)
from lisa.environment import Environment
from lisa.features import Disk
from lisa.messages import DiskPerformanceMessage, DiskSetupType, DiskType
from lisa.node import RemoteNode
from lisa.tools import Lscpu
from microsoft.testsuites.nested.common import (
    connect_nested_vm,
    parse_nested_image_variables,
)
from microsoft.testsuites.performance.common import (
    handle_and_send_back_results,
    reset_partitions,
    reset_raid,
    run_perf_test,
    stop_raid,
)


@TestSuiteMetadata(
    area="storage",
    category="performance",
    description="""
    This test suite is to validate performance of nested VM using FIO tool.
    """,
)
class KVMPerformance(TestSuite):  # noqa
    TIME_OUT = 12000

    @TestCaseMetadata(
        description="""
        This test case is to validate performance of nested VM using fio tool
        with single l1 data disk attached to the l2 VM.
        """,
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=1),
            ),
        ),
    )
    def perf_nested_kvm_storage_singledisk(
        self, node: RemoteNode, environment: Environment, variables: Dict[str, Any]
    ) -> None:
        self._perf_qemu(node, environment, variables, setup_raid=False)

    @TestCaseMetadata(
        description="""
        This test case is to validate performance of nested VM using fio tool with raid0
        configuratrion of 6 l1 data disk attached to the l2 VM.
        """,
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=6),
            ),
        ),
    )
    def perf_nested_kvm_storage_multidisk(
        self, node: RemoteNode, environment: Environment, variables: Dict[str, Any]
    ) -> None:
        self._perf_qemu(node, environment, variables)

    def _perf_qemu(
        self,
        node: RemoteNode,
        environment: Environment,
        variables: Dict[str, Any],
        filename: str = "/dev/sdb",
        start_iodepth: int = 1,
        max_iodepth: int = 1024,
        setup_raid: bool = True,
    ) -> None:
        # get testname from stack
        test_case_name = inspect.stack()[1][3]

        (
            nested_image_username,
            nested_image_password,
            nested_image_port,
            nested_image_url,
        ) = parse_nested_image_variables(variables)

        l1_data_disks = node.features[Disk].get_raw_data_disks()
        l1_data_disk_count = len(l1_data_disks)

        # setup raid on l1 data disks
        if setup_raid:
            disks = ["md0"]
            l1_partition_disks = reset_partitions(node, l1_data_disks)
            stop_raid(node)
            reset_raid(node, l1_partition_disks)
        else:
            disks = ["sdb"]

        # get l2 vm
        l2_vm = connect_nested_vm(
            node,
            nested_image_username,
            nested_image_password,
            nested_image_port,
            nested_image_url,
            disks=disks,
        )

        # Qemu command exits immediately but the VM requires some time to boot up.
        time.sleep(60)
        l2_vm.tools[Lscpu].get_core_count()

        # Each fio process start jobs equal to the iodepth to read/write from
        # the disks. The max number of jobs can be equal to the core count of
        # the node.
        # Examples:
        # iodepth = 4, core count = 8 => max_jobs = 4
        # iodepth = 16, core count = 8 => max_jobs = 8
        num_jobs = []
        iodepth_iter = start_iodepth
        core_count = node.tools[Lscpu].get_core_count()
        while iodepth_iter <= max_iodepth:
            num_jobs.append(min(iodepth_iter, core_count))
            iodepth_iter = iodepth_iter * 2

        # run fio test
        fio_messages: List[DiskPerformanceMessage] = run_perf_test(
            l2_vm,
            start_iodepth,
            max_iodepth,
            filename,
            num_jobs=num_jobs,
            size_gb=8,
            overwrite=True,
        )
        handle_and_send_back_results(
            core_count,
            l1_data_disk_count,
            environment,
            DiskSetupType.raid0,
            DiskType.premiumssd,
            test_case_name,
            fio_messages,
        )
