# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import inspect
import json
import os
from pathlib import PurePosixPath
from pathlib import Path
from typing import Any, Dict, cast


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
from lisa.tools import Fio,Rm

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
        This test case uses fio to test data disk performance with 4K block size.
        """,
        priority=3,
        timeout=TIME_OUT,
    )
    def perf_storage_generic_fio_test(self,
        log: Logger,
        node: Node,
        environment: Environment,
        log_path: Path,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        testcases = variables.get("fio_testcase_list", None)
        if (not testcases):
            testcases_file_path = os.path.join(
                os.path.abspath(__file__).replace(os.path.basename(__file__), ""),
                "default_fio_testcases.json",
            )
            with open(testcases_file_path, "r") as f:
                testcases = json.loads(f.read())["testcases"]

        log.debug(f"Given testcases with params : {testcases}")
        fio = node.tools[Fio]
        rm = node.tools[Rm]
        fio_result = {}

        for testcase in testcases:
            test_name = testcase["testcase_name"]
            fio_result[test_name] = {}
            fio_result[test_name]["runtime_param"] = testcase

            try:
                path = node.get_working_path()

                log.info(f"Executing the FIO testcase : {test_name}")

                name = testcase.get("name", None)
                filename = testcase.get("filename", None)
                mode = testcase.get("mode", None)
                iodepth = testcase.get("iodepth", None)
                numjob = testcase.get("numjob", None)
                time = testcase.get("time", 120)
                ssh_timeout = testcase.get("ssh_timeout", 6400)
                block_size = testcase.get("block_size", "4k")
                size_mb = testcase.get("size_mb", 0)
                direct = testcase.get("direct", True)
                gtod_reduce = testcase.get("gtod_reduce", False)
                ioengine = testcase.get("ioengine", "libaio")
                group_reporting = testcase.get("group_reporting", True)
                overwrite = testcase.get("overwrite", False)
                time_based = testcase.get("time_based", False)

                result = fio.launch(
                    name=name,
                    filename=filename,
                    mode=mode,
                    iodepth=iodepth,
                    numjob=numjob,
                    time=time,
                    ssh_timeout=ssh_timeout,
                    block_size=block_size,
                    size_gb=size_mb,
                    direct=direct,
                    gtod_reduce=gtod_reduce,
                    ioengine=ioengine,
                    group_reporting=group_reporting,
                    overwrite=overwrite,
                    time_based=time_based,
                    cwd=path
                )

                fio_result[test_name]["status"] = "Succeeded"
                fio_result[test_name]["error"] = ""
                fio_result[test_name]["metrics"] = {
                    "qdepth": result.qdepth,
                    "mode": result.mode,
                    "iops": str(result.iops),
                    "latency": str(result.latency),
                    "iodepth": result.iodepth,
                }

            except Exception as e:
                fio_result[test_name]["status"] = "Failed"
                fio_result[test_name]["error"] = str(e)
                fio_result[test_name]["metrics"] = {}
                log.error(e)

            rm.remove_directory(str(path.joinpath(f"{filename}*")), sudo=True)

        log.debug(fio_result)

        # Saving the result
        report_path = node.get_working_path().joinpath("fio_report")
        report_file = report_path.joinpath("fio_test_result.json")
        if not os.path.exists(report_path):
            os.mkdir(report_path)

        with open(report_file, "w") as f:
            f.write(json.dumps(fio_result))

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

        origin_value: Dict[str, str] = {}
        for node in [server_node, client_node]:
            origin_value[node.name] = node.tools[Sysctl].get("fs.aio-max-nr")
            node.tools[Sysctl].write("fs.aio-max-nr", "1048576")
        # run fio test
        perf_disk(
            client_node,
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
        for node in [server_node, client_node]:
            node.tools[Sysctl].write("fs.aio-max-nr", origin_value[node.name])

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
