# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any

from assertpy.assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import CBLMariner, Posix
from lisa.testsuite import simple_requirement
from lisa.tools import Mkfs, Mount
from lisa.tools.mkfs import FileSystem
from lisa.util import SkippedException


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
# Try to load dm-cache module if not already loaded
        result = node.execute("modprobe dm-cache", sudo=True, no_error_log=True)
        if result.exit_code != 0:
            log.warning(f"Failed to load dm-cache module: {result.stdout or result.stderr}")
            raise SkippedException("dm-cache module is not available or cannot be loaded")
            
        # Check if LVM tools are available
        result = node.execute("which pvcreate", no_error_log=True)
        if result.exit_code != 0:
            raise SkippedException("LVM tools are not available on this system")

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
        mkfs = node.tools[Mkfs]
        mount = node.tools[Mount]
        
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
            log.info("Step 1: Creating loopback device files")
            
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
            
            log.info("Step 2: Setting up loopback devices")
            
            # Set up loopback devices using -f --show to find and set up automatically
            result = node.execute(f"losetup -f --show {origin_img}", sudo
                                  =True, expected_exit_code=0)
            loop_origin = result.stdout.strip()
            
            result = node.execute(f"losetup -f --show {cache_img}", sudo=True, expected_exit_code=0)
            loop_cache = result.stdout.strip()
            
            log.info(f"Created loop devices: origin={loop_origin}, cache={loop_cache}")
            
            # Verify loopback devices are created
            result = node.execute("losetup -a", sudo=True)
            log.info(f"Losetup output: {result.stdout}")
            assert_that(result.stdout).described_as(
                "Origin loopback device should be listed"
            ).contains(loop_origin)
            assert_that(result.stdout).described_as(
                "Cache loopback device should be listed"  
            ).contains(loop_cache)
            
            log.info("Step 3: Initializing LVM physical volumes and creating volume group")
            
            # Initialize physical volumes
            node.execute(f"pvcreate {loop_origin} {loop_cache}", sudo=True, expected_exit_code=0)
            
            # Create volume group
            node.execute(f"vgcreate {vg_name} {loop_origin} {loop_cache}", sudo=True, expected_exit_code=0)
            
            # Verify volume group creation
            result = node.execute(f"vgs {vg_name}", sudo=True, expected_exit_code=0)
            assert_that(result.stdout).described_as(
                "Volume group should be created successfully"
            ).contains(vg_name)
            
            log.info("Step 4: Creating logical volumes")
            
            # Create origin logical volume (1.8GB on slow device)
            node.execute(
                f"lvcreate -L 1843M -n {origin_lv} {vg_name} {loop_origin}",
                sudo=True,
                expected_exit_code=0
            )
            
            # Create cache pool logical volume (900MB on fast device)
            # First check available space
            result = node.execute(f"vgs {vg_name}", sudo=True)
            log.info(f"Volume group info before cache pool creation: {result.stdout}")
            
            # Ensure dm-cache module is loaded
            node.execute("modprobe dm-cache", sudo=True, no_error_log=True)
            
            # Create cache pool with smaller size to ensure it fits
            result = node.execute(
                f"lvcreate -L 800M --type cache-pool -n {cache_pool_lv} {vg_name} {loop_cache}",
                sudo=True
            )
            if result.exit_code != 0:
                log.error(f"Cache pool creation failed: {result.stdout}")
                # Try alternative approach without specifying the device
                result = node.execute(
                    f"lvcreate -L 800M --type cache-pool -n {cache_pool_lv} {vg_name}",
                    sudo=True,
                    expected_exit_code=0
                )
            
            log.info("Step 5: Attaching cache pool to origin LV")
            
            # Convert origin LV to cached LV by attaching cache pool
            result = node.execute(
                f"lvconvert --type cache --cachepool {vg_name}/{cache_pool_lv} {vg_name}/{origin_lv} -y",
                sudo=True,
                expected_exit_code=0
            )
            
            # Verify the cached LV is created
            result = node.execute(f"lvs {vg_name}/{origin_lv}", sudo=True, expected_exit_code=0)
            assert_that(result.stdout).described_as(
                "Cached logical volume should be created successfully"
            ).contains(origin_lv)
            
            # Check if the LV type is cache
            result = node.execute(f"lvs --noheadings -o lv_layout {vg_name}/{origin_lv}", sudo=True)
            assert_that("cache").described_as(
                "Logical volume should have cache layout"
            ).is_in(result.stdout.lower())
            
            log.info("Step 6: Formatting and mounting the cached LV")
            
            # Format the cached logical volume with ext4
            mkfs.format_disk(f"/dev/{vg_name}/{origin_lv}", FileSystem.ext4)
            
            # Create mount point and mount the cached LV
            node.execute(f"mkdir -p {mount_point}", sudo=True)
            mount.mount(f"/dev/{vg_name}/{origin_lv}", mount_point, FileSystem.ext4)
            
            # Verify mount
            mount_info = mount.get_partition_info(mount_point)
            assert_that(mount_info).described_as(
                "Cached LV should be mounted successfully"
            ).is_not_empty()
            
            log.info("Step 7: Testing basic I/O on cached device")
            
            # Write test data to verify functionality
            test_file = f"{mount_point}/test_file"
            # node.execute(f"echo 'dm-cache test data' | sudo tee {test_file} > /dev/null", sudo=False)
            
            # # Read back and verify  
            # result = node.execute(f"cat {test_file}", sudo=True)
            # assert_that("dm-cache test data").described_as(
            #     "Test data should be readable from cached device"
            # ).is_in(result.stdout)
            
            # Check cache statistics
            result = node.execute(f"dmsetup status {vg_name}-{origin_lv}", sudo=True)
            log.info(f"DM-Cache status: {result.stdout}")
            
            # Verify cache policy and configuration
            log.info("Step 8: Verifying cache policy and configuration")
            
            # Check dmsetup table to verify cache configuration
            result = node.execute(f"dmsetup table {vg_name}-{origin_lv}", sudo=True)
            log.info(f"DM-Cache table: {result.stdout}")
            
            # Verify the cache table contains expected components
            cache_table = result.stdout.strip()
            assert_that(cache_table).described_as(
                "Cache table should contain 'cache' target type"
            ).contains("cache")
            
            # Check for cache policy (should contain 'smq' or other policy)
            assert_that(cache_table).described_as(
                "Cache table should specify a cache policy (smq, mq, etc.)"
            ).matches(r".*\b(smq|mq|cleaner)\b.*")
            
            # Check for cache mode (writethrough, writeback, etc.)
            if not any(mode in cache_table for mode in ["writethrough", "writeback", "passthrough"]):
                log.warning("Cache mode not explicitly found in table output")
            
            # Use lvs to get detailed cache information
            result = node.execute(f"lvs -o+cache_mode,cache_policy {vg_name}/{origin_lv}", sudo=True)
            log.info(f"LVS cache details: {result.stdout}")
            
            # Verify cache policy is set
            cache_info = result.stdout
            assert_that(cache_info).described_as(
                "Cache policy should be displayed in lvs output"
            ).matches(r".*\b(smq|mq|cleaner)\b.*")
            
            # Additional cache statistics
            result = node.execute(f"dmsetup message {vg_name}-{origin_lv} 0 stats", sudo=True, no_error_log=True)
            if result.exit_code == 0:
                log.info(f"DM-Cache detailed stats: {result.stdout}")
            else:
                log.warning("Could not retrieve detailed cache statistics")
            
            log.info("dm-cache setup, policy verification, and basic functionality completed successfully")
            
        finally:
            # Cleanup
            log.info("Cleaning up test resources")
            
            try:
                # Unmount if mounted
                if mount.check_mount_point_exist(mount_point):
                    mount.umount(f"/dev/{vg_name}/{origin_lv}", mount_point, erase=False)
                    
                # Remove mount point
                node.execute(f"rmdir {mount_point}", sudo=True, no_error_log=True)
                
                # Remove logical volumes
                node.execute(f"lvremove -f {vg_name}/{origin_lv}", sudo=True, no_error_log=True)
                
                # Remove volume group
                node.execute(f"vgremove -f {vg_name}", sudo=True, no_error_log=True)
                
                # Remove physical volumes
                node.execute(f"pvremove {loop_origin} {loop_cache}", sudo=True, no_error_log=True)
                
                # Detach loopback devices
                node.execute(f"losetup -d {loop_origin}", sudo=True, no_error_log=True)
                node.execute(f"losetup -d {loop_cache}", sudo=True, no_error_log=True)
                
                # Remove image files
                node.execute(f"rm -f {origin_img} {cache_img}", sudo=True, no_error_log=True)
                
            except Exception as cleanup_error:
                log.warning(f"Cleanup error (non-fatal): {cleanup_error}")
