# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import inspect
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, cast

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
    simple_requirement,
)
from lisa.features import Disk, IsolatedResource
from lisa.features.network_interface import Sriov, Synthetic
from lisa.messages import DiskSetupType, DiskType
from lisa.node import RemoteNode
from lisa.operating_system import SLES, Debian, Redhat
from lisa.testsuite import TestResult
from lisa.tools import FileSystem, Lscpu, Mkfs, Mount, NFSClient, NFSServer, Sysctl
from lisa.util import SkippedException
from microsoft.testsuites.performance.common import (
    perf_disk,
    reset_partitions,
    reset_raid,
    stop_raid,
)


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
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=16),
            ),
            supported_features=[IsolatedResource],
        ),
    )
    def perf_premium_datadisks_4k(self, node: Node, result: TestResult) -> None:
        self._perf_premium_datadisks(node, result)

    @TestCaseMetadata(
        description="""
        This test case uses fio to test data disk performance using 1024K block size.
        """,
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=16),
            ),
            supported_features=[IsolatedResource],
        ),
    )
    def perf_premium_datadisks_1024k(self, node: Node, result: TestResult) -> None:
        self._perf_premium_datadisks(node, result, block_size=1024)

    @TestCaseMetadata(
        description="""
        This test case uses fio to test vm with 24 data disks.
        """,
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=24),
            ),
            supported_features=[IsolatedResource],
        ),
    )
    def perf_premium_datadisks_io(self, node: Node, result: TestResult) -> None:
        self._perf_premium_datadisks(
            node,
            result,
            max_iodepth=64,
            filename="/dev/sdc",
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
                data_disk_size=search_space.IntRange(min=10),
            ),
            network_interface=Sriov(),
        ),
    )
    def perf_storage_over_nfs_sriov_tcp_4k(self, result: TestResult) -> None:
        self._perf_nfs(result)

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
                data_disk_size=search_space.IntRange(min=10),
            ),
            network_interface=Sriov(),
        ),
    )
    def perf_storage_over_nfs_sriov_udp_4k(self, result: TestResult) -> None:
        self._perf_nfs(result, protocol="udp")

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
                data_disk_size=search_space.IntRange(min=10),
            ),
            network_interface=Synthetic(),
        ),
    )
    def perf_storage_over_nfs_synthetic_tcp_4k(self, result: TestResult) -> None:
        self._perf_nfs(result)

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
                data_disk_size=search_space.IntRange(min=10),
            ),
            network_interface=Synthetic(),
        ),
    )
    def perf_storage_over_nfs_synthetic_udp_4k(self, result: TestResult) -> None:
        self._perf_nfs(result, protocol="udp")


    @TestCaseMetadata(
        description="""
        This test case uses fio to test data disk performance.
        """,
        priority=3,
        timeout=TIME_OUT,
    )
    def perf_storage_generic_fio_test(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        log_path: Path,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        testcases = variables.get("fio_testcase_list", None)
        if not testcases or len(testcases) == 0:
            # Run default testcases
            for size in [512, 4096]:
                id = str(uuid.uuid4())
                start_iodepth = 1
                max_iodepth = 4
                num_jobs = []

                core_count = node.tools[Lscpu].get_core_count()
                iodepth_iter = start_iodepth
                while iodepth_iter <= max_iodepth:
                    num_jobs.append(min(iodepth_iter, core_count))
                    iodepth_iter = iodepth_iter * 2

                perf_disk(
                    node=node,
                    start_iodepth=start_iodepth,
                    max_iodepth=max_iodepth,
                    filename=f"{size}_MB_FIO_{id}",
                    test_result=result,
                    test_name=f"{size}_MB_4K",
                    num_jobs=num_jobs,
                    block_size=4,
                    time=240,
                    size_mb=size,
                )
        else:
            for testcase in testcases:
                id = str(uuid.uuid4())
                try:
                    start_iodepth = testcase.get("start_iodepth", 1)
                    max_iodepth = testcase.get("max_iodepth", 1)
                    num_jobs = []
                    iodepth_iter = start_iodepth
                    core_count = node.tools[Lscpu].get_core_count()
                    while iodepth_iter <= max_iodepth:
                        num_jobs.append(min(iodepth_iter, core_count))
                        iodepth_iter = iodepth_iter * 2

                    time = testcase.get("time", 240)
                    block_size = testcase.get("block_size", 4)
                    size_mb = testcase.get("size_mb", 512)
                    overwrite = testcase.get("overwrite", False)

                    test_name = f"{size_mb}_MB_{block_size}K"
                    log.debug(f"Executing the FIO testcase : {test_name}")

                    perf_disk(
                        node=node,
                        start_iodepth=start_iodepth,
                        max_iodepth=max_iodepth,
                        filename=f"{size_mb}_MB_FIO_{id}",
                        test_result=result,
                        test_name=test_name,
                        num_jobs=num_jobs,
                        block_size=block_size,
                        time=time,
                        size_mb=size_mb,
                        overwrite=overwrite,
                    )
                except Exception as e:
                    log.error(e)

    def _configure_nfs(
        self,
        server: RemoteNode,
        client: RemoteNode,
        server_raid_disk_name: str = "/dev/md0",
        server_raid_disk_mount_dir: str = "/mnt",
        client_nfs_mount_dir: str = "/mnt/nfs_client_share",
        protocol: str = "tcp",
    ) -> None:
        # mount raid disk on server
        server.shell.mkdir(PurePosixPath(server_raid_disk_mount_dir), exist_ok=True)
        server.tools[Mkfs].format_disk(server_raid_disk_name, FileSystem.ext4)
        server.tools[Mount].mount(
            server_raid_disk_name, server_raid_disk_mount_dir, options="nobarrier"
        )

        # setup nfs on server
        server.tools[NFSServer].create_shared_dir(
            [client.internal_address], server_raid_disk_mount_dir
        )

        # setup raid on client
        client.tools[NFSClient].setup(
            server.internal_address,
            server_raid_disk_mount_dir,
            client_nfs_mount_dir,
            f"proto={protocol},vers=3",
        )

    def _run_fio_on_nfs(
        self,
        test_result: TestResult,
        server: RemoteNode,
        client: RemoteNode,
        server_data_disk_count: int,
        client_nfs_mount_dir: str,
        core_count: int,
        num_jobs: List[int],
        start_iodepth: int = 1,
        max_iodepth: int = 1024,
        filename: str = "fiodata",
        block_size: int = 4,
    ) -> None:
        origin_value: Dict[str, str] = {}
        for node in [server, client]:
            origin_value[node.name] = node.tools[Sysctl].get("fs.aio-max-nr")
            node.tools[Sysctl].write("fs.aio-max-nr", "1048576")
        perf_disk(
            client,
            start_iodepth,
            max_iodepth,
            filename,
            test_name=inspect.stack()[1][3],
            core_count=core_count,
            disk_count=server_data_disk_count,
            disk_setup_type=DiskSetupType.raid0,
            disk_type=DiskType.premiumssd,
            num_jobs=num_jobs,
            block_size=block_size,
            size_mb=256,
            overwrite=True,
            cwd=PurePosixPath(client_nfs_mount_dir),
            test_result=test_result,
        )
        for node in [server, client]:
            node.tools[Sysctl].write("fs.aio-max-nr", origin_value[node.name])

    def _perf_nfs(
        self,
        test_result: TestResult,
        server_raid_disk_name: str = "/dev/md0",
        server_raid_disk_mount_dir: str = "/mnt/nfs_share",
        client_nfs_mount_dir: str = "/mnt/nfs_client_share",
        protocol: str = "tcp",
        filename: str = "fiodata",
        block_size: int = 4,
        start_iodepth: int = 1,
        max_iodepth: int = 1024,
    ) -> None:
        environment = test_result.environment
        assert environment, "fail to get environment from testresult"

        server_node = cast(RemoteNode, environment.nodes[0])
        client_node = cast(RemoteNode, environment.nodes[1])

        # Run test only on Debian, SLES and Redhat distributions
        if (
            not isinstance(server_node.os, Redhat)
            and not isinstance(server_node.os, Debian)
            and not isinstance(server_node.os, SLES)
        ):
            raise SkippedException(f"{server_node.os.name} not supported")

        # refer below link, in RHEL 8, NFS over UDP is no longer supported.
        # https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/deploying_different_types_of_servers/exporting-nfs-shares_deploying-different-types-of-servers#the-tcp-and-udp-protocols-in-nfsv3-and-nfsv4_exporting-nfs-shares  # noqa: E501
        if (
            "udp" == protocol
            and isinstance(server_node.os, Redhat)
            and server_node.os.information.version >= "8.0.0"
        ):
            raise SkippedException(
                f"udp mode not supported on {server_node.os.information.vendor} "
                f"{server_node.os.information.release}"
            )

        # Each fio process start jobs equal to the iodepth to read/write from
        # the disks. The max number of jobs can be equal to the core count of
        # the node.
        # Examples:
        # iodepth = 4, core count = 8 => max_jobs = 4
        # iodepth = 16, core count = 8 => max_jobs = 8
        num_jobs = []
        iodepth_iter = start_iodepth
        core_count = client_node.tools[Lscpu].get_core_count()
        while iodepth_iter <= max_iodepth:
            num_jobs.append(min(iodepth_iter, core_count))
            iodepth_iter = iodepth_iter * 2

        # setup raid on server
        server_data_disks = server_node.features[Disk].get_raw_data_disks()
        server_data_disk_count = len(server_data_disks)
        server_partition_disks = reset_partitions(server_node, server_data_disks)
        reset_raid(server_node, server_partition_disks)

        try:
            self._configure_nfs(
                server_node,
                client_node,
                server_raid_disk_name=server_raid_disk_name,
                server_raid_disk_mount_dir=server_raid_disk_mount_dir,
                client_nfs_mount_dir=client_nfs_mount_dir,
                protocol=protocol,
            )

            # run fio test
            self._run_fio_on_nfs(
                test_result,
                server_node,
                client_node,
                server_data_disk_count,
                client_nfs_mount_dir,
                core_count,
                num_jobs,
                start_iodepth=start_iodepth,
                max_iodepth=max_iodepth,
                filename=filename,
                block_size=block_size,
            )
        finally:
            # clean up
            # stop nfs server and client
            server_node.tools[NFSServer].stop()
            client_node.tools[NFSClient].stop(mount_dir=client_nfs_mount_dir)
            server_node.tools[Mount].umount(
                server_raid_disk_name, server_raid_disk_mount_dir
            )

    def _perf_premium_datadisks(
        self,
        node: Node,
        test_result: TestResult,
        block_size: int = 4,
        max_iodepth: int = 256,
        filename: str = "/dev/md0",
    ) -> None:
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        disk_count = len(data_disks)
        assert_that(disk_count).described_as(
            "At least 1 data disk for fio testing."
        ).is_greater_than(0)
        partition_disks = reset_partitions(node, data_disks)
        reset_raid(node, partition_disks)
        cpu = node.tools[Lscpu]
        core_count = cpu.get_core_count()
        start_iodepth = 1
        perf_disk(
            node,
            start_iodepth,
            max_iodepth,
            filename,
            test_name=inspect.stack()[1][3],
            core_count=core_count,
            disk_count=disk_count,
            disk_setup_type=DiskSetupType.raid0,
            disk_type=DiskType.premiumssd,
            numjob=core_count,
            block_size=block_size,
            size_mb=8192,
            overwrite=True,
            test_result=test_result,
        )

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs.pop("node")
        stop_raid(node)
