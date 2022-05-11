# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any, List

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
from lisa.tools import Fdisk, FileSystem, Mdadm, Mkfs, Mount


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


def _make_mount_raid(node: Node, disk_list: List[str]) -> None:
    mdadm = node.tools[Mdadm]
    mdadm.create_raid(disk_list)
    mkfs = node.tools[Mkfs]
    mkfs.format_disk("/dev/md0", FileSystem.ext4)
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
                disk_type=schema.DiskType.StandardHDDLRS,
                data_disk_iops=search_space.IntRange(min=500),
                data_disk_count=search_space.IntRange(min=64),
            ),
        ),
    )
    def verify_disk_with_nobarrier(self, node: Node, environment: Environment) -> None:
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        disk_count = len(data_disks)
        assert_that(disk_count).described_as(
            "At least 1 data disk for testing."
        ).is_greater_than(0)
        partition_disks = _format_disk(node, data_disks)
        _stop_raid(node)
        _make_mount_raid(node, partition_disks)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs.pop("node")
        mount = node.tools[Mount]
        mount.umount("/dev/md0", "/data")
        _stop_raid(node)
