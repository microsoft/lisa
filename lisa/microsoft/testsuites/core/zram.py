# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePosixPath
from typing import Any

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.base_tools import Cat
from lisa.operating_system import BSD, CBLMariner, Windows
from lisa.sut_orchestrator import AZURE, HYPERV, READY
from lisa.tools import Echo, Lsmod, Mkfs, Modprobe, Mount
from lisa.tools.mkfs import FileSystem
from lisa.tools.rm import Rm
from lisa.util import UnsupportedDistroException


@TestSuiteMetadata(
    area="core",
    category="functional",
    description="""
    This test suite validates zram compression algorithm support.
    It verifies that the kernel can load zram with crypto_zstd and
    crypto_lz4 compression backends and that zram devices function
    correctly with each algorithm.
    """,
    requirement=simple_requirement(
        supported_platform_type=[AZURE, HYPERV, READY],
        unsupported_os=[BSD, Windows],
    ),
    tags=["AZURE_LINUX"],
)
class ZramCompression(TestSuite):
    # zram device path used for testing
    _ZRAM_DEVICE = "/dev/zram0"
    # 256 MB test disk size
    _ZRAM_SIZE_BYTES = "268435456"
    _ZRAM_MOUNT_POINT = "/mnt/zram_test"
    _COMP_ALGORITHM_PATH = PurePosixPath("/sys/block/zram0/comp_algorithm")
    _DISKSIZE_PATH = PurePosixPath("/sys/block/zram0/disksize")
    _RESET_PATH = PurePosixPath("/sys/block/zram0/reset")

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        if not isinstance(node.os, CBLMariner) or node.os.information.version < "3.0.0":
            raise SkippedException(
                UnsupportedDistroException(
                    node.os,
                    "zram compression test requires Azure Linux 3.0+.",
                )
            )

    @TestCaseMetadata(
        description="""
        Verify zram works with the zstd compression algorithm.
        Steps:
        1. Load the crypto_zstd kernel module.
        2. Load the zram kernel module with num_devices=1.
        3. Set the compression algorithm to zstd on /dev/zram0.
        4. Set the disk size and verify the device is usable.
        5. Reset and clean up the zram device.
        """,
        priority=3,
    )
    def verify_zram_crypto_zstd(self, node: Node) -> None:
        self._test_zram_compression(node, module="crypto_zstd", algorithm="zstd")

    @TestCaseMetadata(
        description="""
        Verify zram works with the lz4 compression algorithm.
        Steps:
        1. Load the crypto_lz4 kernel module.
        2. Load the zram kernel module with num_devices=1.
        3. Set the compression algorithm to lz4 on /dev/zram0.
        4. Set the disk size and verify the device is usable.
        5. Reset and clean up the zram device.
        """,
        priority=3,
    )
    def verify_zram_crypto_lz4(self, node: Node) -> None:
        self._test_zram_compression(node, module="crypto_lz4", algorithm="lz4")

    def _test_zram_compression(self, node: Node, module: str, algorithm: str) -> None:
        modprobe = node.tools[Modprobe]

        # Check that the crypto module exists in the kernel
        if not modprobe.module_exists(module):
            raise SkippedException(f"Kernel module '{module}' is not available.")

        # Check that zram module exists
        if not modprobe.module_exists("zram"):
            raise SkippedException("Kernel module 'zram' is not available.")

        try:
            # Load the crypto compression module
            modprobe.load(module)
            node.log.info(f"Loaded kernel module: {module}")

            # Ensure clean state: remove any existing zram device
            modprobe.remove(["zram"], ignore_error=True)

            # Load zram with a single device
            modprobe.load("zram", parameters="num_devices=1")
            node.log.info("Loaded zram module with num_devices=1")

            # Set the compression algorithm
            node.tools[Echo].write_to_file(
                algorithm,
                self._COMP_ALGORITHM_PATH,
                sudo=True,
                ignore_error=False,
            )

            # Verify the active algorithm (marked with brackets)
            comp_output = node.tools[Cat].read(
                str(self._COMP_ALGORITHM_PATH), force_run=True, sudo=True
            )
            assert_that(comp_output).described_as(
                f"Expected '{algorithm}' to be active "
                f"(in brackets), got: {comp_output}"
            ).contains(f"[{algorithm}]")
            node.log.info(f"Compression algorithm set to: {algorithm}")

            # Set the disk size
            node.tools[Echo].write_to_file(
                self._ZRAM_SIZE_BYTES,
                self._DISKSIZE_PATH,
                sudo=True,
                ignore_error=False,
            )

            # Verify disk size was applied
            disksize = node.tools[Cat].read(
                str(self._DISKSIZE_PATH), force_run=True, sudo=True
            )
            assert_that(int(disksize.strip())).described_as(
                "zram disk size should match requested value"
            ).is_equal_to(int(self._ZRAM_SIZE_BYTES))

            # Format and mount the zram device
            node.tools[Mkfs].format_disk(self._ZRAM_DEVICE, FileSystem.ext4)
            node.tools[Mount].mount(
                self._ZRAM_DEVICE,
                self._ZRAM_MOUNT_POINT,
                fs_type=FileSystem.ext4,
            )

            # Write test data and read it back
            test_string = "zram_compression_validation"
            test_file = PurePosixPath(f"{self._ZRAM_MOUNT_POINT}/testfile")
            node.tools[Echo].write_to_file(
                test_string,
                test_file,
                sudo=True,
                ignore_error=False,
            )
            read_back = node.tools[Cat].read(str(test_file), sudo=True)
            assert_that(read_back.strip()).described_as(
                "Data read from zram should match written data"
            ).is_equal_to(test_string)

            node.log.info(
                f"zram with '{algorithm}' compression: write/read validation passed"
            )

            # Verify the module is loaded in the kernel
            lsmod = node.tools[Lsmod]
            assert_that(lsmod.module_exists("zram", force_run=True)).described_as(
                "zram module should be loaded"
            ).is_true()

        finally:
            # Clean up: unmount, reset zram, unload modules
            mount_tool = node.tools[Mount]
            if mount_tool.check_mount_point_exist(self._ZRAM_MOUNT_POINT):
                mount_tool.umount("zram0", self._ZRAM_MOUNT_POINT, erase=False)
            node.tools[Rm].remove_directory(self._ZRAM_MOUNT_POINT, sudo=True)
            node.tools[Echo].write_to_file("1", self._RESET_PATH, sudo=True)
            modprobe.remove(["zram"], ignore_error=True)
            modprobe.remove([module], ignore_error=True)
