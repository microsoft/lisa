# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import inspect
from pathlib import PurePosixPath
from typing import Any, List, cast

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
    simple_requirement,
)
from lisa.environment import Environment
from lisa.features import Disk
from lisa.features.network_interface import Sriov, Synthetic
from lisa.messages import DiskPerformanceMessage, DiskSetupType, DiskType
from lisa.node import RemoteNode
from lisa.operating_system import SLES, Debian, Redhat
from lisa.tools import (
    FIOMODES,
    Fdisk,
    FileSystem,
    Fio,
    Lscpu,
    Mdadm,
    Mkfs,
    Mount,
    NFSClient,
    NFSServer,
)
from lisa.util import SkippedException
from microsoft.testsuites.performance.common import (
    handle_and_send_back_results,
    run_perf_test,
)


def _format_disk(
    node: Node,
    disk_list: List[str],
) -> List[str]:
    fdisk = node.tools[Fdisk]
    partition_disks: List[str] = []
    for data_disk in disk_list:
        fdisk.delete_partitions(data_disk)
        partition_disks.append(fdisk.make_partition(data_disk, format=False))
    return partition_disks


def _stop_raid(node: Node) -> None:
    mdadm = node.tools[Mdadm]
    mdadm.stop_raid()


def _make_raid(node: Node, disk_list: List[str]) -> None:
    mdadm = node.tools[Mdadm]
    mdadm.create_raid(disk_list)


@TestSuiteMetadata(
    area="storage",
    category="performance",
    description="""
    This test suite is to validate premium SSD data disks performance of Linux VM using
     fio tool.
    """,
)
class StoragePerformance(TestSuite):
    TIME_OUT = 12000

    @TestCaseMetadata(
        description="""
        This test case uses fio to test data disk performance with 4K block size.
        """,
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            min_core_count=72,
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=5000,
                data_disk_count=search_space.IntRange(min=16),
            ),
        ),
    )
    def perf_premium_datadisks_4k(self, node: Node, environment: Environment) -> None:
        self._perf_premium_datadisks(
            node, environment, test_case_name="perf_premium_datadisks_4k"
        )

    @TestCaseMetadata(
        description="""
        This test case uses fio to test data disk performance using 1024K block size.
        """,
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            min_core_count=72,
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=5000,
                data_disk_count=search_space.IntRange(min=16),
            ),
        ),
    )
    def perf_premium_datadisks_1024k(
        self, node: Node, environment: Environment
    ) -> None:
        self._perf_premium_datadisks(
            node,
            environment,
            block_size=1024,
            test_case_name="perf_premium_datadisks_1024k",
        )

    @TestCaseMetadata(
        description="""
        This test case uses fio to test vm with 24 data disks.
        """,
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            min_core_count=72,
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=24),
            ),
        ),
    )
    def perf_premium_datadisks_io(self, node: Node, environment: Environment) -> None:
        self._perf_premium_datadisks(
            node,
            environment,
            test_case_name="perf_premium_datadisks_io",
            max_iodepth=64,
        )

    @TestCaseMetadata(
        description="""
        This test case uses fio to test performance of nfs server over TCP with
        VM's initialized with SRIOV network interface.
        """,
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            min_count=2,
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=12),
            ),
            network_interface=Sriov(),
        ),
    )
    def perf_storage_over_nfs_sriov_tcp_4k(self, environment: Environment) -> None:
        self._perf_nfs(
            environment,
        )

    @TestCaseMetadata(
        description="""
        This test case uses fio to test performance of nfs server over UDP with
        VM's initialized with SRIOV network interface.
        """,
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            min_count=2,
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=12),
            ),
            network_interface=Sriov(),
        ),
    )
    def perf_storage_over_nfs_sriov_udp_4k(self, environment: Environment) -> None:
        self._perf_nfs(
            environment,
            protocol="udp",
        )

    @TestCaseMetadata(
        description="""
        This test case uses fio to test performance of nfs server over TCP with
        VM's initialized with synthetic network interface.
        """,
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            min_count=2,
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=12),
            ),
            network_interface=Synthetic(),
        ),
    )
    def perf_storage_over_nfs_synthetic_tcp_4k(self, environment: Environment) -> None:
        self._perf_nfs(environment)

    @TestCaseMetadata(
        description="""
        This test case uses fio to test performance of nfs server over UDP with
        VM's initialized with synthetic network interface.
        """,
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            min_count=2,
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=12),
            ),
            network_interface=Synthetic(),
        ),
    )
    def perf_storage_over_nfs_synthetic_udp_4k(self, environment: Environment) -> None:
        self._perf_nfs(
            environment,
            protocol="udp",
        )

    def _perf_nfs(
        self,
        environment: Environment,
        server_raid_disk_name: str = "/dev/md0",
        server_raid_disk_mount_dir: str = "/mnt/nfs_share",
        client_nfs_mount_dir: str = "/mnt/nfs_client_share",
        protocol: str = "tcp",
        filename: str = "fiodata",
        block_size: int = 4,
        start_iodepth: int = 1,
        max_iodepth: int = 1024,
        ssh_timeout: int = TIME_OUT,
    ) -> None:
        server_node = cast(RemoteNode, environment.nodes[0])
        client_node = cast(RemoteNode, environment.nodes[1])

        # get testname from stack
        test_case_name = inspect.stack()[1][3]

        # Run test only on Debian, SLES and Redhat distributions
        if (
            not isinstance(server_node.os, Redhat)
            and not isinstance(server_node.os, Debian)
            and not isinstance(server_node.os, SLES)
        ):
            raise SkippedException(f"{server_node.os} not supported")

        # calculate the number of jobs to run. The max number of jobs is equal
        # to the core count of the node.
        num_jobs = []
        core_count = client_node.tools[Lscpu].get_core_count()
        for i in range(start_iodepth, max_iodepth + 1):
            num_jobs.append(min(2 ** (i - 1), core_count))

        # setup raid on server
        server_data_disks = server_node.features[Disk].get_raw_data_disks()
        server_data_disk_count = len(server_data_disks)
        server_partition_disks = _format_disk(server_node, server_data_disks)
        _stop_raid(server_node)
        _make_raid(server_node, server_partition_disks)

        # mount raid disk on server
        server_node.shell.mkdir(
            PurePosixPath(server_raid_disk_mount_dir), exist_ok=True
        )
        server_node.tools[Mkfs].format_disk(server_raid_disk_name, FileSystem.ext4)
        server_node.tools[Mount].mount(
            server_raid_disk_name, server_raid_disk_mount_dir, options="nobarrier"
        )

        # setup nfs on server
        server_node.tools[NFSServer].create_shared_dir(
            [client_node.internal_address], server_raid_disk_mount_dir
        )

        # setup raid on client
        client_node.tools[NFSClient].setup(
            server_node.internal_address,
            server_raid_disk_mount_dir,
            client_nfs_mount_dir,
            protocol,
        )

        # Run a dummy fio job on client to create required test files and
        # transfer over network. If this step is skipped, it can impact
        # the test result.
        client_node.tools[Fio].launch(
            name="prepare",
            filename=filename,
            mode=FIOMODES.read.name,
            ssh_timeout=ssh_timeout,
            size_gb=1024,
            block_size="1M",
            iodepth=128,
            overwrite=True,
            numjob=8,
            cwd=PurePosixPath(client_nfs_mount_dir),
        )

        # run fio test
        fio_messages: List[DiskPerformanceMessage] = run_perf_test(
            client_node,
            start_iodepth,
            max_iodepth,
            filename,
            num_jobs=num_jobs,
            block_size=block_size,
            size_gb=1024,
            overwrite=True,
            cwd=PurePosixPath(client_nfs_mount_dir),
        )
        handle_and_send_back_results(
            core_count,
            server_data_disk_count,
            environment,
            DiskSetupType.raid0,
            DiskType.premiumssd,
            test_case_name,
            fio_messages,
            block_size,
        )

    def _perf_premium_datadisks(
        self,
        node: Node,
        environment: Environment,
        test_case_name: str,
        block_size: int = 4,
        max_iodepth: int = 256,
    ) -> None:
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        disk_count = len(data_disks)
        assert_that(disk_count).described_as(
            "At least 1 data disk for fio testing."
        ).is_greater_than(0)
        partition_disks = _format_disk(node, data_disks)
        _stop_raid(node)
        _make_raid(node, partition_disks)
        filename = "/dev/md0"
        cpu = node.tools[Lscpu]
        core_count = cpu.get_core_count()
        start_iodepth = 1
        fio_messages: List[DiskPerformanceMessage] = run_perf_test(
            node,
            start_iodepth,
            max_iodepth,
            filename,
            numjob=core_count,
            block_size=block_size,
            size_gb=1024,
            overwrite=True,
        )
        handle_and_send_back_results(
            core_count,
            disk_count,
            environment,
            DiskSetupType.raid0,
            DiskType.premiumssd,
            test_case_name,
            fio_messages,
            block_size,
        )

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs.pop("node")
        _stop_raid(node)
