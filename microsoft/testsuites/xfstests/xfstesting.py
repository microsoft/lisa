# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa import (
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
    simple_requirement,
)
from lisa.features import Disk, Nvme
from lisa.operating_system import Debian, Redhat, Suse
from lisa.tools import Fdisk, FileSystem, Mkfs, Mount, Parted, Uname, Xfstests

_scratch_folder = "/root/scratch"
_test_folder = "/root/test"


def _skip_test(node: Node) -> None:
    if not (
        isinstance(node.os, Redhat)
        or isinstance(node.os, Suse)
        or isinstance(node.os, Debian)
    ):
        raise SkippedException(
            f"Current distro {node.os.name} doesn't support xfstesting."
        )


def _configure_disk(
    node: Node,
    disk_name: str,
    first_disk: str,
    second_disk: str,
    first_mountpoint: str = _test_folder,
    second_mountpoint: str = _scratch_folder,
    file_system: FileSystem = FileSystem.xfs,
) -> None:
    mount = node.tools[Mount]
    fdisk = node.tools[Fdisk]
    parted = node.tools[Parted]
    mkfs = node.tools[Mkfs]
    fdisk.delete_partitions(disk_name)
    for mountpoint in [first_mountpoint, second_mountpoint]:
        node.execute(f"rm -r {mountpoint}", sudo=True)

    mount.umount(first_disk, first_mountpoint)
    mount.umount(second_disk, second_mountpoint)

    parted.make_label(disk_name)
    parted.make_partition(disk_name, "primary", "1", "50%")
    parted.make_partition(disk_name, "secondary", "50%", "100%")

    for disk in [first_disk, second_disk]:
        mkfs.format_disk(disk, file_system)

    for mountpoint in [first_mountpoint, second_mountpoint]:
        node.execute(f"mkdir {mountpoint}", sudo=True)


@TestSuiteMetadata(
    area="storage",
    category="community",
    description="""
    This test suite is to validate different types of data disk on Linux VM
     using xfstests.
    """,
)
class Xfstesting(TestSuite):
    # Use xfstests benchmark to test the different types of data disk,
    #  it will run many cases, so the runtime is longer than usual case.
    TIME_OUT = 14400
    # exclude btrfs/244 temporarily for below commit not picked up by distro vendor.
    # https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/commit/fs/btrfs/volumes.c?id=e4571b8c5e9ffa1e85c0c671995bd4dcc5c75091 # noqa: E501
    EXCLUDED_TESTS = (
        "generic/211 generic/430 generic/431 generic/434 /xfs/438 xfs/490"
        + " btrfs/007 btrfs/178 btrfs/244"
    )

    @TestCaseMetadata(
        description="""
        This test case will run generic xfstests testing against
         standard data disk with xfs type system.
        """,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.StandardHDDLRS,
                data_disk_iops=500,
                data_disk_count=search_space.IntRange(min=1),
            ),
        ),
        timeout=TIME_OUT,
        priority=3,
    )
    def xfstesting_generic_standard_datadisk_validation(self, node: Node) -> None:
        _skip_test(node)
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        self._execute_xfstests(
            node,
            data_disks[0],
            f"{data_disks[0]}1",
            f"{data_disks[0]}2",
            excluded_tests=self.EXCLUDED_TESTS,
        )

    @TestCaseMetadata(
        description="""
        This test case will run xfs xfstests testing against
         standard data disk with xfs type system.
        """,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.StandardHDDLRS,
                data_disk_iops=500,
                data_disk_count=search_space.IntRange(min=1),
            ),
        ),
        timeout=TIME_OUT,
        priority=3,
    )
    def xfstesting_xfs_standard_datadisk_validation(self, node: Node) -> None:
        _skip_test(node)
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        self._execute_xfstests(
            node,
            data_disks[0],
            f"{data_disks[0]}1",
            f"{data_disks[0]}2",
            test_type=FileSystem.xfs.name,
            excluded_tests=self.EXCLUDED_TESTS,
        )

    @TestCaseMetadata(
        description="""
        This test case will run ext4 xfstests testing against
         standard data disk with ext4 type system.
        """,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.StandardHDDLRS,
                data_disk_iops=500,
                data_disk_count=search_space.IntRange(min=1),
            ),
        ),
        timeout=TIME_OUT,
        priority=3,
    )
    def xfstesting_ext4_standard_datadisk_validation(self, node: Node) -> None:
        _skip_test(node)
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        self._execute_xfstests(
            node,
            data_disks[0],
            f"{data_disks[0]}1",
            f"{data_disks[0]}2",
            file_system=FileSystem.ext4,
            test_type=FileSystem.ext4.name,
        )

    @TestCaseMetadata(
        description="""
        This test case will run btrfs xfstests testing against
         standard data disk with btrfs type system.
        """,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.StandardHDDLRS,
                data_disk_iops=500,
                data_disk_count=search_space.IntRange(min=1),
            ),
        ),
        timeout=TIME_OUT,
        priority=3,
    )
    def xfstesting_btrfs_standard_datadisk_validation(self, node: Node) -> None:
        _skip_test(node)
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        self._execute_xfstests(
            node,
            data_disks[0],
            f"{data_disks[0]}1",
            f"{data_disks[0]}2",
            file_system=FileSystem.btrfs,
            test_type=FileSystem.btrfs.name,
            excluded_tests=self.EXCLUDED_TESTS,
        )

    @TestCaseMetadata(
        description="""
        This test case will run generic xfstests testing against
         nvme data disk with xfs type system.
        """,
        timeout=TIME_OUT,
        priority=3,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def xfstesting_generic_nvme_datadisk_validation(self, node: Node) -> None:
        _skip_test(node)
        nvme_disk = node.features[Nvme]
        nvme_data_disks = nvme_disk.get_raw_data_disks()
        self._execute_xfstests(
            node,
            nvme_data_disks[0],
            f"{nvme_data_disks[0]}p1",
            f"{nvme_data_disks[0]}p2",
            excluded_tests=self.EXCLUDED_TESTS,
        )

    @TestCaseMetadata(
        description="""
        This test case will run xfs xfstests testing against
         nvme data disk with xfs type system.
        """,
        timeout=TIME_OUT,
        priority=3,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def xfstesting_xfs_nvme_datadisk_validation(self, node: Node) -> None:
        _skip_test(node)
        nvme_disk = node.features[Nvme]
        nvme_data_disks = nvme_disk.get_raw_data_disks()
        self._execute_xfstests(
            node,
            nvme_data_disks[0],
            f"{nvme_data_disks[0]}p1",
            f"{nvme_data_disks[0]}p2",
            test_type=FileSystem.xfs.name,
        )

    @TestCaseMetadata(
        description="""
        This test case will run ext4 xfstests testing against
         nvme data disk with ext4 type system.
        """,
        timeout=TIME_OUT,
        priority=3,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def xfstesting_ext4_nvme_datadisk_validation(self, node: Node) -> None:
        _skip_test(node)
        nvme_disk = node.features[Nvme]
        nvme_data_disks = nvme_disk.get_raw_data_disks()
        self._execute_xfstests(
            node,
            nvme_data_disks[0],
            f"{nvme_data_disks[0]}p1",
            f"{nvme_data_disks[0]}p2",
            file_system=FileSystem.ext4,
            test_type=FileSystem.ext4.name,
        )

    @TestCaseMetadata(
        description="""
        This test case will run btrfs xfstests testing against
         nvme data disk with btrfs type system.
        """,
        timeout=TIME_OUT,
        priority=3,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def xfstesting_btrfs_nvme_datadisk_validation(self, node: Node) -> None:
        _skip_test(node)
        nvme_disk = node.features[Nvme]
        nvme_data_disks = nvme_disk.get_raw_data_disks()
        self._execute_xfstests(
            node,
            nvme_data_disks[0],
            f"{nvme_data_disks[0]}p1",
            f"{nvme_data_disks[0]}p2",
            file_system=FileSystem.btrfs,
            test_type=FileSystem.btrfs.name,
            excluded_tests=self.EXCLUDED_TESTS,
        )

    def _execute_xfstests(
        self,
        node: Node,
        data_disk: str,
        test_dev: str,
        scratch_dev: str,
        file_system: FileSystem = FileSystem.xfs,
        test_type: str = "generic",
        excluded_tests: str = "",
    ) -> None:
        # exclude this case generic/641 temporarily
        # it will trigger oops on RHEL8.3/8.4, VM will reboot
        # lack of commit 5808fecc572391867fcd929662b29c12e6d08d81
        if (
            test_type == "generic"
            and isinstance(node.os, Redhat)
            and node.os.information.version >= "8.3.0"
        ):
            excluded_tests += " generic/641"

        if test_type == FileSystem.btrfs.name:
            uname_tool = node.tools[Uname]
            kernel_ver = uname_tool.get_linux_information().kernel_version
            config_path = f"/boot/config-{kernel_ver}"
            config = "CONFIG_BTRFS_FS=y|CONFIG_BTRFS_FS=m"
            result = node.execute(
                f"grep -E '{config}' /boot/config-$(uname -r) {config_path}",
                shell=True,
                sudo=True,
            )
            if result.exit_code != 0:
                raise SkippedException(
                    "Current distro doesn't support btrfs file system."
                )

        _configure_disk(node, data_disk, test_dev, scratch_dev, file_system=file_system)
        xfstests = node.tools[Xfstests]
        xfstests.set_local_config(scratch_dev, _scratch_folder, test_dev, _test_folder)
        xfstests.set_excluded_tests(excluded_tests)
        node.execute(
            f"bash check -g {test_type}/quick -E exclude.txt",
            sudo=True,
            shell=True,
            cwd=xfstests.get_xfstests_path(),
            timeout=self.TIME_OUT,
        )
