# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from lisa import Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.tools import Fdisk, Mount, Parted, Xfstests
from lisa.tools.fdisk import FileSystem


def _configure_disk(
    node: Node,
    disk_name: str,
    first_mountpoint: str = "/root/test",
    second_mountpoint: str = "/root/scratch",
    file_system: FileSystem = FileSystem.xfs,
) -> None:
    node.execute(f"rm -r {first_mountpoint}", sudo=True)
    node.execute(f"rm -r {second_mountpoint}", sudo=True)
    mount = node.tools[Mount]
    first_disk = f"{disk_name}1"
    second_disk = f"{disk_name}2"
    fdisk = node.tools[Fdisk]
    parted = node.tools[Parted]

    mount.umount(first_disk, first_mountpoint)
    mount.umount(second_disk, second_mountpoint)

    parted.make_label(disk_name)
    parted.make_partition(disk_name, "primary", "1", "50%")
    parted.make_partition(disk_name, "secondary", "50%", "100%")
    fdisk.make_partition(first_disk, file_system)
    fdisk.make_partition(second_disk, file_system)
    node.execute(f"mkdir {first_mountpoint}", sudo=True)
    node.execute(f"mkdir {second_mountpoint}", sudo=True)


@TestSuiteMetadata(
    area="storage",
    category="community",
    description="""
    This test suite is to validate different data disk on Linux VM using xfstests.
    """,
)
class xfstests(TestSuite):
    TIME_OUT = 7200

    @TestCaseMetadata(
        description="""
        This test case will
        """,
        priority=2,
    )
    def xfstests_xfs_standard_datadisk_validation(self, node: Node) -> None:
        xfstests = node.tools[Xfstests]
        cmd_result = node.execute(
            "readlink -f /dev/disk/azure/scsi1/*", shell=True, sudo=True
        )
        _configure_disk(node, cmd_result.stdout)
        tool_path = xfstests.get_xfstests_config_path()
        node.execute(
            f"echo 'SCRATCH_DEV=/dev/sdc2' >> {tool_path}", sudo=True, shell=True
        )
        node.execute(
            f"echo 'SCRATCH_MNT=/root/scratch' >> {tool_path}", sudo=True, shell=True
        )
        node.execute(f"echo 'TEST_DEV=/dev/sdc1' >> {tool_path}", sudo=True, shell=True)
        node.execute(
            "export TEST_DIR=/root/test && "
            "bash check -g generic/quick -E exclude.txt > xfstests.log",
            sudo=True,
            shell=True,
            cwd=xfstests.get_tool_path().joinpath("xfstests-dev"),
            timeout=7200,
        )
