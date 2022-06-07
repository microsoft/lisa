# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import Any

from assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import CentOs, Redhat
from lisa.sut_orchestrator.azure.tools import LisDriver
from lisa.testsuite import simple_requirement
from lisa.tools import Cat, Df, Fallocate, Modinfo, Rpm, Stat, Uname, Wget
from lisa.util import (
    LisaException,
    SkippedException,
    UnsupportedDistroException,
    get_matched_str,
)


@TestSuiteMetadata(
    area="lis",
    category="functional",
    description="""
        This test suite contains tests that are dependent on an LIS driver
    """,
    requirement=simple_requirement(
        supported_os=[
            CentOs,
            Redhat,
        ]
    ),
)
class Lis(TestSuite):
    # '#define HV_DRV_VERSION	"4.3.4"' -> 4.3.4
    version_pattern = re.compile(r'"(.+)"')
    # '#define _HV_DRV_VERSION 0x1B2' -> 0x1B2
    hex_version_pattern = re.compile(r"(0x\w+)")

    @TestCaseMetadata(
        description="""
            Downloads header files based on the LIS version and compares the installed
             LIS version to the expected one which is found in the header files.

            Steps:
            1. Check for RPM
            2. Capture installed LIS version on the node
            3. For each rhel version (5,6,7), it downloads the header file and compares
             the LIS version in the header file with the LIS version installed
        """,
        priority=1,
    )
    def verify_lis_driver_version(self, node: Node, log: Logger) -> None:
        cat = node.tools[Cat]
        modinfo_tool = node.tools[Modinfo]
        wget_tool = node.tools[Wget]
        self._check_lis_installable(node)

        # Checking for RPM Package Manager
        rpm_qa = node.execute("rpm -qa").stdout
        if ("kmod-microsoft-hyper-v" not in rpm_qa) or (
            "microsoft-hyper-v" not in rpm_qa
        ):
            raise SkippedException("No LIS RPM's are detected. Skipping test.")

        # Capturing LIS version from the node
        version = modinfo_tool.get_version(mod_name='"hv_vmbus"').strip()

        for i in range(5, 8):
            node.execute("rm -rf hv_compat.h")
            wget_tool.get(
                "https://raw.githubusercontent.com/LIS/lis-next/"
                f"{version}/hv-rhel{i}.x/hv/include/linux/hv_compat.h",
                filename="hv_compat.h",
                file_path="./",
            )

            # Capturing the LIS version from the source code
            source_version = cat.read_with_filter(
                "hv_compat.h", "define HV_DRV_VERSION"
            )
            source_version = get_matched_str(source_version, self.version_pattern)

            # Capturing the LIS version in hex from the source code
            source_version_hex = source_version = cat.read_with_filter(
                "hv_compat.h", "define _HV_DRV_VERSION"
            )
            source_version_hex = get_matched_str(
                source_version_hex, self.hex_version_pattern
            )

            self._check_lis_version(node, version, source_version, log)
            self._check_lis_version_hex(node, version, source_version_hex, log)

    @TestCaseMetadata(
        description="""
            This test case is to verify LIS RPM installation script to check the disk
             space before proceeding to LIS install.
            This avoids half / corrupted installations.

            Steps:
            1. Test leaves "bare minimum" size available for LIS install and checks if
             LIS installation is successful.
        """,
        priority=2,
    )
    def verify_lis_preinstall_disk_size_positive(self, node: Node, log: Logger) -> None:
        self._verify_lis_preinstall_disk_size(node, log)

    @TestCaseMetadata(
        description="""
            This test case is to verify LIS RPM installation script to check the disk
             space before proceeding to LIS install.
            This avoids half / corrupted installations.

            Steps:
            1. Test leaves "non installable" size on disk and checks if ./install.sh
             script skips the installation of not.
        """,
        priority=2,
    )
    def verify_lis_preinstall_disk_size_negative(self, node: Node, log: Logger) -> None:
        self._verify_lis_preinstall_disk_size(node, log, test_type="negative")

    def _verify_lis_preinstall_disk_size(
        self, node: Node, log: Logger, test_type: str = "positive"
    ) -> None:
        lisdriver = self._check_lis_installable(node)
        fallocate = node.tools[Fallocate]
        stat = node.tools[Stat]
        df = node.tools[Df]
        rpm = node.tools[Rpm]
        cmd_result = lisdriver.uninstall_from_iso()
        if 0 != cmd_result.exit_code:
            raise LisaException("fail to uninstall lis")
        self._clean_up_files(node)
        lib_module_folder = "/lib/modules"
        boot_folder = "/boot"
        # fetched from spec
        min_space_for_ramfs_creation = 157286400
        # 9MB to hit rpm limit
        min_sz_root_partition_not_root = 9437184
        # 10MB for log file creation
        root_partition_buffer_space = 10485760
        # allowed limit of +- 1MB
        boot_partition_buffer_space = 1048576
        root_partition = df.get_partition_by_mountpoint("/")
        boot_partition = df.get_partition_by_mountpoint("/boot")
        assert root_partition, "fail to get root partition"
        assert boot_partition, "fail to get boot partition"
        ramdisk_size_factor = 1
        if root_partition.name != boot_partition.name:
            ramdisk_size_factor = 2
        lis_path = lisdriver.download()
        os_version = node.os.information.release.split(".")
        version = os_version[0] + os_version[1]
        lib_module_required_space = rpm.get_file_size(
            f"{lis_path}/RPMS{version}/kmod-microsoft-hyper*x86_64.rpm"
        )
        uname = node.tools[Uname]
        kernel_version = uname.get_linux_information().kernel_version_raw
        ramdisk_required_space = stat.get_total_size(
            f"/boot/initramfs-{kernel_version}.img"
        )
        boot_part_required_space = ramdisk_required_space + boot_partition_buffer_space
        root_part_required_space = (
            min_space_for_ramfs_creation
            + ramdisk_size_factor * ramdisk_required_space
            + lib_module_required_space
            + root_partition_buffer_space
        )
        node.execute("sync")
        fblock_non_root = stat.get_fs_available_size(lib_module_folder)
        fblock_root = stat.get_fs_free_blocks(lib_module_folder)
        boot_part_avail_space = stat.get_fs_block_size(
            boot_folder
        ) * stat.get_fs_available_size(boot_folder)
        root_part_avail_space = (
            stat.get_fs_block_size(lib_module_folder) * fblock_non_root
        )
        if test_type == "negative":
            boot_part_required_space = int(boot_part_required_space / 2)
            root_part_required_space = int(root_part_required_space / 2)
            # 6.X distro RPM does not use root user space free space.
            # Hence setting the min limit.
            if fblock_non_root != fblock_root:
                root_part_required_space = min_sz_root_partition_not_root
            single_partition_file_size = (
                root_part_avail_space - root_part_required_space
            )
            fallocate.create_file(single_partition_file_size, "/lib/modules/file.out")
        if boot_partition != root_partition:
            single_partition_file_size_boot = (
                boot_part_avail_space - boot_part_required_space
            )
            fallocate.create_file(single_partition_file_size_boot, "/boot/file.out")
        result = lisdriver.install_from_iso()
        if test_type == "negative":
            if result.exit_code == 0:
                raise LisaException(
                    "lis should fail to be installed for insufficient space"
                )
            else:
                log.debug(f"fail to install lis for reason {result.stdout}")
        self._clean_up_files(node)
        if test_type == "positive":
            lisdriver.uninstall_from_iso()

    # Returns true if version and source_version are the same
    def _check_lis_version(
        self, node: Node, version: str, source_version: str, log: Logger
    ) -> None:
        log.debug("Detected modinfo version is {version}")
        log.debug("Version found in source code is {source_version}")

        assert_that(version).described_as(
            "Detected version and Source version are different. Expected LIS version:"
            f" {source_version}, Actual LIS version: {version}"
        )

    # Returns true if version and source_version_hex are the same
    def _check_lis_version_hex(
        self, node: Node, version: str, source_version_hex: str, log: Logger
    ) -> None:
        log.debug("Detected modinfo version is {version}")
        log.debug("Version found in source code is {source_version}")

        # The below two lines are converting the inputted LIS version to hex
        version_hex = version.replace(".", "")
        version_hex = str(hex(int(version_hex))).lower()

        # Converting to lower for consistency
        source_version_hex = source_version_hex.lower()

        assert_that(version).described_as(
            "Detected version and Source version are different for hex value. Expected"
            f" LIS version: {source_version_hex}, Actual LIS version: {version_hex}"
        )

    def _check_lis_installable(self, node: Node) -> LisDriver:
        try:
            lisdriver = node.tools[LisDriver]
            return lisdriver
        except UnsupportedDistroException as err:
            raise SkippedException(err)

    def _clean_up_files(self, node: Node) -> None:
        node.execute("rm -f /lib/modules/file.out", sudo=True)
        node.execute("rm -f /boot/file.out", sudo=True)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs.pop("node")
        self._clean_up_files(node)
