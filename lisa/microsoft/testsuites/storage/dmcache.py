# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any

from assertpy.assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import CBLMariner, Posix
from lisa.testsuite import simple_requirement
from lisa.tools import Mkdir, Mkfs, Modprobe, Mount
from lisa.tools.mkfs import FileSystem
from lisa.util import SkippedException
from lisa.tools.losetup import Losetup
from lisa.tools.pvcreate import Pvcreate
from lisa.tools.vgcreate import Vgcreate
from lisa.tools.lvcreate import Lvcreate
from lisa.tools.lvconvert import Lvconvert
from lisa.tools.lvs import Lvs
from lisa.tools.lvremove import Lvremove
from lisa.tools.vgremove import Vgremove
from lisa.tools.pvremove import Pvremove
from lisa.tools.dmsetup import Dmsetup



@TestSuiteMetadata(
    area="dmcache",
    category="functional",
    description="""
    This test suite validates dm-cache functionality using LVM on Azure VMs.
    It sets up a dm-cache configuration to verify that caching is functional
    and provides performance benefits.
    """,
)
class DmCacheTestSuite(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        
        # Check if this is a POSIX system
        assert isinstance(node.os, Posix), f"{node.os} is not supported"
        
        # Try to load dm-cache module if not already loaded
        modprobe = node.tools[Modprobe]
        try:
            modprobe.load("dm-cache")
        except AssertionError:
            log.warning("Failed to load dm-cache module")
            raise SkippedException("dm-cache module is not available or cannot be loaded")
            
        # Check if LVM tools are available
        # result = node.execute("which pvcreate", no_error_log=True)
        # if result.exit_code != 0:
        #     raise SkippedException("LVM tools are not available on this system")

    @TestCaseMetadata(
        description="""
        This test verifies dm-cache functionality by:
        1. Creating loopback devices to simulate slow origin and fast cache disks
        2. Setting up LVM physical volumes and volume groups
        3. Creating logical volumes for origin and cache pool
        4. Attaching cache pool to origin LV to enable caching
        5. Formatting and mounting the cached logical volume
        6. Verifying the dm-cache setup is working correctly
        """,
        priority=2,
        requirement=simple_requirement(
            supported_os=[CBLMariner],
        ),
    )
    def verify_dm_cache_setup(
        self,
        node: Node,
        log: Logger,
    ) -> None:
        # Initialize tools

        mkdir = node.tools[Mkdir]
        mkfs = node.tools[Mkfs]
        mount = node.tools[Mount]
        losetup = node.tools[Losetup]
        pvcreate = node.tools[Pvcreate]
        vgcreate = node.tools[Vgcreate]
        lvcreate = node.tools[Lvcreate]
        lvconvert = node.tools[Lvconvert]
        lvs = node.tools[Lvs]
        lvremove = node.tools[Lvremove]
        vgremove = node.tools[Vgremove]
        pvremove = node.tools[Pvremove]
        dmsetup = node.tools[Dmsetup]


        # Define file paths and device names
        origin_img = "/root/origin.img"
        cache_img = "/root/cache.img"
        vg_name = "vgtest"
        origin_lv = "origin"
        cache_pool_lv = "cachepool"
        mount_point = "/mnt/testcache"
        loop_origin = ""
        loop_cache = ""

        try:
            log.info("Creating loopback device files")
            # Create origin disk image (2GB - slow device)
            node.execute(
                f"dd if=/dev/zero of={origin_img} bs=1M count=2048",
                sudo=True,
                expected_exit_code=0
            )
            # Create cache disk image (1GB - fast device)
            node.execute(
                f"dd if=/dev/zero of={cache_img} bs=1M count=1024",
                sudo=True,
                expected_exit_code=0
            )

            log.info("Setting up loopback devices")
            loop_origin = losetup.attach(origin_img)
            loop_cache = losetup.attach(cache_img)
            log.info(f"Created loop devices: origin={loop_origin}, cache={loop_cache}")
            losetup_output = losetup.list()
            log.info(f"Losetup output: {losetup_output}")
            assert_that(losetup_output).described_as(
                "Origin loopback device should be listed"
            ).contains(loop_origin)
            assert_that(losetup_output).described_as(
                "Cache loopback device should be listed"  
            ).contains(loop_cache)

            log.info("Initializing LVM physical volumes and creating volume group")
            pvcreate.create_pv(loop_origin, loop_cache)
            vgcreate.create_vg(vg_name, loop_origin, loop_cache)
            result = node.execute(f"vgs {vg_name}", sudo=True, expected_exit_code=0)
            assert_that(result.stdout).described_as(
                "Volume group should be created successfully"
            ).contains(vg_name)

            log.info("Creating logical volumes")
            # Create origin LV on the slow device (loop_origin)
            lvcreate.create_lv("1843M", origin_lv, vg_name, loop_origin)
            result = node.execute(f"vgs {vg_name}", sudo=True)
            log.info(f"Volume group info before cache pool creation: {result.stdout}")
            # Create cache pool on the fast device (loop_cache)
            lvcreate.create_lv("800M", cache_pool_lv, vg_name, loop_cache, extra="--type cache-pool")
            log.info("Cache pool created successfully")
            
            # Verify device placement: origin on loop_origin, cache pool data on loop_cache
            lv_info = lvs.get_lv_info(vg_name, options="-a -o+devices")
            log.info(f"Logical volumes and their devices (including hidden LVs):\n{lv_info}")
            # Check that origin is on loop_origin
            assert_that(lv_info).described_as(
                f"Origin LV should be on {loop_origin}"
            ).contains(origin_lv).contains(loop_origin)
            # Check that cache pool data (_cdata) is on loop_cache
            assert_that(lv_info).described_as(
                f"Cache pool data should be on {loop_cache}"
            ).contains("cachepool_cdata").contains(loop_cache)

            log.info("Attaching cache pool to origin LV")
            lvconvert.attach_cache(vg_name, origin_lv, cache_pool_lv, yes=True)
            lv_info = lvs.get_lv_info(f"{vg_name}/{origin_lv}")
            assert_that(lv_info).described_as(
                "Cached logical volume should be created successfully"
            ).contains(origin_lv)
            lv_layout = lvs.get_lv_layout(vg_name, origin_lv)
            assert_that("cache").described_as(
                "Logical volume should have cache layout"
            ).is_in(lv_layout.lower())

            log.info("Formatting and mounting the cached LV")
            mkfs.format_disk(f"/dev/{vg_name}/{origin_lv}", FileSystem.ext4)
            mkdir.create_directory(mount_point, sudo=True)
            mount.mount(f"/dev/{vg_name}/{origin_lv}", mount_point, FileSystem.ext4)
            mount_info = mount.get_partition_info(mount_point)
            assert_that(mount_info).described_as(
                "Cached LV should be mounted successfully"
            ).is_not_empty()

            dm_status = dmsetup.status(f"{vg_name}-{origin_lv}")
            log.info(f"DM-Cache status: {dm_status}")

            log.info("Verifying cache policy and configuration")
            dm_table = dmsetup.table(f"{vg_name}-{origin_lv}")
            log.info(f"DM-Cache table: {dm_table}")
            cache_table = dm_table.strip()
            assert_that(cache_table).described_as(
                "Cache table should contain 'cache' target type"
            ).contains("cache")
            assert_that(cache_table).described_as(
                "Cache table should specify a cache policy (smq, mq, etc.)"
            ).matches(r".*\b(smq|mq|cleaner)\b.*")
            if not any(mode in cache_table for mode in ["writethrough", "writeback", "passthrough"]):
                log.warning("Cache mode not explicitly found in table output")
            cache_info = lvs.get_lv_info(f"{vg_name}/{origin_lv}", options="-o+cache_mode,cache_policy")
            log.info(f"LVS cache details: {cache_info}")
            assert_that(cache_info).described_as(
                "Cache policy should be displayed in lvs output"
            ).matches(r".*\b(smq|mq|cleaner)\b.*")
            
            # Get detailed cache statistics from dmsetup status output
            # The status output already contains useful cache statistics
            dm_status = dmsetup.status(f"{vg_name}-{origin_lv}")
            status_parts = dm_status.strip().split()
            if len(status_parts) > 3 and status_parts[2] == "cache":
                # Parse cache statistics from status output
                # Format: start length cache metadata_mode <cache stats> policy policy_args...
                cache_stats = " ".join(status_parts[3:])
                log.info(f"DM-Cache statistics: {cache_stats}")
            
            log.info("dm-cache setup, policy verification, and basic functionality completed successfully")

        finally:
            log.info("Cleaning up test resources")
            try:
                if mount.check_mount_point_exist(mount_point):
                    mount.umount(f"/dev/{vg_name}/{origin_lv}", mount_point, erase=False)
                node.execute(f"rmdir {mount_point}", sudo=True, no_error_log=True)
                lvremove.remove_lv(f"{vg_name}/{origin_lv}", force=True, ignore_errors=True)
                vgremove.remove_vg(vg_name, force=True, ignore_errors=True)
                pvremove.remove_pv(loop_origin, loop_cache, force=True, ignore_errors=True)
                losetup.detach(loop_origin)
                losetup.detach(loop_cache)
                node.execute(f"rm -f {origin_img} {cache_img}", sudo=True, no_error_log=True)
            except Exception as cleanup_error:
                log.warning(f"Cleanup error (non-fatal): {cleanup_error}")
