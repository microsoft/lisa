# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import Any, List, Union

from assertpy import assert_that

from lisa import (
    LisaException,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
    simple_requirement,
)
from lisa.features import Disk
from lisa.operating_system import BSD, Windows
from lisa.tools import Fdisk, FileSystem, Fio, Mdadm, Mkfs, Mount
from lisa.util import find_patterns_in_lines


def _format_disk(
    node: Node,
    disk_list: List[str],
    first_partition_size: str = "",
    second_partition_size: str = "",
) -> List[str]:
    fdisk = node.tools[Fdisk]
    partition_disks: List[str] = []
    for data_disk in disk_list:
        fdisk.delete_partitions(data_disk)
        partition_disks.append(
            fdisk.make_partition(
                data_disk,
                format_=False,
                first_partition_size=first_partition_size,
                second_partition_size=second_partition_size,
            )
        )
    return partition_disks


def _stop_raid(node: Node) -> None:
    mdadm = node.tools[Mdadm]
    mdadm.stop_raid()


def _make_mount_raid(
    node: Node,
    disk_list: List[str],
    level: Union[int, str] = 0,
    do_mount: bool = True,
    do_mkfs: bool = True,
    force_run: bool = False,
    shell: bool = False,
) -> None:
    mdadm = node.tools[Mdadm]
    mdadm.create_raid(disk_list, level=level, force_run=force_run, shell=shell)
    if do_mkfs:
        mkfs = node.tools[Mkfs]
        mkfs.format_disk("/dev/md0", FileSystem.ext4)
    if do_mount:
        mount = node.tools[Mount]
        mount.mount("/dev/md0", "/data", options="nobarrier")


@TestSuiteMetadata(
    area="storage",
    category="functional",
    description="""
    This test suite is to validate storage function in Linux VM.
    """,
)
class StorageTest(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case is to
            1. Make raid0 based on StandardHDDLRS disks.
            2. Mount raid0 with nobarrier options.
        """,
        priority=3,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.StandardHDDLRS,
                os_disk_type=schema.DiskType.StandardHDDLRS,
                data_disk_iops=search_space.IntRange(min=500),
                data_disk_count=search_space.IntRange(min=64),
            ),
            unsupported_os=[Windows, BSD],
        ),
    )
    def verify_disk_with_nobarrier(self, node: Node) -> None:
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        disk_count = len(data_disks)
        assert_that(disk_count).described_as(
            "At least 1 data disk for testing."
        ).is_greater_than(0)
        partition_disks = _format_disk(node, data_disks)
        _stop_raid(node)
        _make_mount_raid(node, partition_disks)

    @TestCaseMetadata(
        description="""
        This test case is to
            1. Attach 2 512GB premium SSD disks
            2. Create a 100GB partition for each disk using fdisk
            3. Create a RAID type 1 device using partitions created in step 2
            4. Run fio against raid0 with verify option for 100 times
        """,
        priority=1,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=2300),
                data_disk_count=search_space.IntRange(min=2),
            ),
            unsupported_os=[Windows, BSD],
        ),
    )
    def verify_disk_with_fio_verify_option(self, node: Node) -> None:
        pattern = re.compile(
            r"error=Invalid or incomplete multibyte or wide character", re.M
        )
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        disk_count = len(data_disks)
        assert_that(disk_count).described_as(
            "At least 2 data disk for testing."
        ).is_greater_than(1)
        partition_disks = _format_disk(node, data_disks, second_partition_size="+100G")
        _stop_raid(node)
        # keep the level as "mirror", the bug only happens on mirror level
        _make_mount_raid(
            node,
            partition_disks,
            level="mirror",
            do_mount=False,
            do_mkfs=False,
            force_run=True,
            shell=True,
        )
        for _ in range(100):
            try:
                node.tools[Fio].launch(
                    name="test",
                    filename="/dev/md0",
                    mode="write",
                    iodepth=16,
                    numjob=0,
                    time=0,
                    block_size="",
                    size_gb=100,
                    group_reporting=False,
                    do_verify=True,
                    bsrange="512-256K",
                    verify_dump=True,
                    verify_fatal=True,
                    verify="md5",
                )
            except LisaException as e:
                matched = find_patterns_in_lines(str(e), [pattern])
                if matched[0]:
                    raise LisaException(
                        "This is a bug in the Linux block layer merging BIOs that"
                        " go across the page boundary. This bug was introduced in"
                        " Linux 5.1 when the block layer BIO page tracking is enhanced"
                        " to support multiple pages. Please pick up this commit "
                        "https://patchwork.kernel.org/project/linux-block/patch/1623094445-22332-1-git-send-email-longli@linuxonhyperv.com/"  # noqa: E501
                    )
                raise e

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs.pop("node")
        mount = node.tools[Mount]
        mount.umount("/dev/md0", "/data")
        _stop_raid(node)
