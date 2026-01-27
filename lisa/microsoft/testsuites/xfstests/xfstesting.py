# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""
Xfstesting Test Suite Module
============================

This module contains the Xfstesting test suite for validating filesystem
functionality using the xfstests benchmark tool on various disk types.

Test Categories:
----------------
1. **Standard Data Disk Tests**: Tests against Azure Standard HDD disks
   - verify_generic_standard_datadisk (xfs)
   - verify_generic_ext4_standard_datadisk (ext4)
   - verify_xfs_standard_datadisk (xfs-specific)
   - verify_ext4_standard_datadisk (ext4-specific)
   - verify_btrfs_standard_datadisk (btrfs-specific)

2. **NVMe Data Disk Tests**: Tests against NVMe disks
   - verify_generic_nvme_datadisk (xfs)
   - verify_generic_ext4_nvme_datadisk (ext4)
   - verify_xfs_nvme_datadisk (xfs-specific)
   - verify_ext4_nvme_datadisk (ext4-specific)
   - verify_btrfs_nvme_datadisk (btrfs-specific)

3. **Azure File Share Tests**: Tests against Azure Files (SMB/CIFS)
   - verify_azure_file_share (parallel execution with multiple workers)

Parallel Execution for Azure File Share (January 2026 Enhancement):
-------------------------------------------------------------------
The verify_azure_file_share test uses parallel execution to reduce runtime.
This is controlled by the `_default_worker_count` variable.

**IMPORTANT: _default_worker_count ONLY affects verify_azure_file_share**

Other tests (data disk, NVMe) continue to use sequential execution via
the `_execute_xfstests()` method and are NOT affected by this variable.

The `after_case()` method does reference `_default_worker_count` for cleanup,
but this is defensive/best-effort cleanup wrapped in try/except blocks:
- For non-parallel tests: cleanup attempts fail silently (resources don't exist)
- For parallel tests: cleanup properly removes worker directories and mounts

Benefits of Parallel Execution:
-------------------------------
1. **Reduced Runtime**: ~45+ min → ~24 min (3 workers) or ~18 min (4 workers)
2. **Better Resource Utilization**: Azure File Share tests are I/O bound,
   not CPU bound, making parallelization effective
3. **Isolated Workers**: Each worker has its own xfstests copy and file shares,
   preventing race conditions and state conflicts

Configuration:
--------------
- `_default_worker_count`: Number of parallel workers (default: 4)
- Each worker gets its own Azure File Share pair (test + scratch)
- Tests are distributed round-robin across workers
- Results are aggregated after all workers complete

Known Limitations:
------------------
- Round-robin distribution doesn't account for test duration variability
- Some tests (e.g., generic/007: 285s) are much slower than others (0-5s)
- This can cause worker imbalance; future work: runtime-aware distribution
"""
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, cast

from microsoft.testsuites.xfstests.xfstests import (
    DEFAULT_WORKER_BASE_DIR,
    Xfstests,
    XfstestsParallelRunner,
)

from lisa import (
    Logger,
    Node,
    RemoteNode,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    UnsupportedDistroException,
    schema,
    search_space,
    simple_requirement,
)
from lisa.environment import Environment
from lisa.features import Disk, Nvme
from lisa.operating_system import BSD, CBLMariner, Oracle, Redhat, Windows
from lisa.sut_orchestrator import AZURE, HYPERV
from lisa.sut_orchestrator.azure.features import AzureFileShare, Nfs
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.testsuite import TestResult
from lisa.tools import Echo, FileSystem, KernelConfig, Mkfs, Mount, Parted
from lisa.util import (
    BadEnvironmentStateException,
    LisaException,
    constants,
    generate_random_chars,
)

# =============================================================================
# Global Configuration Variables
# =============================================================================

# Section : NFS options. <TODO>
_default_nfs_mount = "vers=4,minorversion=1,_netdev,nofail,sec=sys 0 0"
_default_nfs_excluded_tests: str = ""
_default_nfs_testcases: str = ""
# Section : SMB options.
_default_smb_mount = (
    "vers=3.11,dir_mode=0755,file_mode=0755,serverino,nosharesock"
    ",mfsymlinks,max_channels=4,actimeo=30"
)
# Excluded tests for Azure Files SMB:
# Reference: https://learn.microsoft.com/azure/storage/files/
#            files-smb-protocol#limitations
#
# Azure Files SMB does NOT support:
# - Sparse files (FSCTL_SET_SPARSE not implemented)
# - Hard links (link() syscall fails)
# - Symbolic links (native; mfsymlinks mount option provides emulation)
# - mknod/mkfifo (no device nodes, FIFOs, or sockets)
# - Hole punching / fallocate (FALLOC_FL_PUNCH_HOLE not supported)
# - POSIX chmod (mode set via mount options only)
# - File cloning / reflink (CoW not supported)
# - Extended attributes (native; mfsymlinks provides partial support)
#
_default_smb_excluded_tests: str = (
    # =========================================================================
    # Section 1: Original exclusions - features unsupported by Azure Files SMB
    # These tests require filesystem features not available on SMB/CIFS
    # =========================================================================
    "generic/015 generic/019 generic/027 generic/034 generic/039 generic/040 "
    "generic/041 generic/050 generic/056 generic/057 generic/059 generic/065 "
    "generic/066 generic/067 generic/073 generic/076 generic/081 generic/083 "
    "generic/090 generic/096 generic/101 generic/102 generic/104 generic/106 "
    "generic/107 generic/108 generic/114 generic/204 generic/218 generic/223 "
    "generic/224 generic/226 generic/250 generic/252 generic/269 generic/273 "
    "generic/274 generic/275 generic/299 generic/300 generic/311 generic/312 "
    "generic/320 generic/321 generic/322 generic/325 generic/335 generic/336 "
    "generic/338 generic/341 generic/342 generic/343 generic/347 generic/348 "
    "generic/361 generic/371 generic/376 generic/388 generic/405 generic/409 "
    "generic/410 generic/411 generic/416 generic/418 generic/427 generic/441 "
    "generic/442 generic/455 generic/456 generic/459 generic/466 generic/470 "
    "generic/475 generic/481 generic/482 generic/483 generic/484 generic/487 "
    "generic/488 generic/489 generic/500 generic/510 generic/512 generic/520 "
    "generic/534 generic/535 generic/536 generic/547 generic/552 generic/557 "
    "generic/558 generic/559 generic/560 generic/561 generic/562 generic/570 "
    "generic/586 generic/589 generic/619 generic/620 generic/640 "
    # =========================================================================
    # Section 2: cifs-specific test exclusions
    # =========================================================================
    # cifs/001: Tests file cloning (reflink/CoW) - not supported on Azure Files
    #           Error: "clone failed: Operation not supported"
    "cifs/001 "
    # =========================================================================
    # Section 3: Auto-skipped tests moved to explicit exclusion
    # These tests auto-skip at runtime but excluding explicitly saves time
    # =========================================================================
    # Sparse files not supported (FSCTL_SET_SPARSE not implemented):
    "generic/014 generic/129 generic/130 generic/239 generic/240 "
    # POSIX chmod not supported on cifs (mode set via mount options):
    "generic/125 generic/598 "
    # mknod/mkfifo not supported (no device nodes, FIFOs, sockets):
    "generic/184 generic/306 "
    # mkfs_sized not applicable (cloud filesystem, cannot run mkfs):
    "generic/211 "
    # Hole punching (fallocate PUNCH_HOLE) not supported:
    "generic/469 generic/567 "
    # =========================================================================
    # Section 4: Known failures on Azure Files SMB
    # =========================================================================
    # generic/013: fsstress with link=10 - uses hard links not supported by SMB
    #              Phase 3 runs: -f link=10 which calls link() syscall
    #              Azure Files does not support hard links, causing test failure
    "generic/013 "
    # generic/346: mmap concurrent writes produce data corruption over SMB
    #              Memory-mapped file coherency across threads not guaranteed
    #              Error: thread offset mismatch due to SMB caching semantics
    "generic/346 "
    # generic/524: XFS-specific writeback race condition test
    #              Tests XFS delalloc block accounting, not applicable to SMB
    #              Runtime varies wildly (6s to 330s) based on network conditions
    "generic/524"
)
# Test cases for Azure Files SMB validation.
# These tests validate SMB functionality that Azure Files supports.
# generic/070: Extended attribute stress test (attr_set, attr_remove)
#              - Works with mfsymlinks mount option providing xattr-like support
_default_smb_testcases: str = (
    "generic/001 generic/005 generic/006 generic/007 generic/010 generic/011 "
    "generic/024 generic/028 generic/029 generic/030 generic/036 "
    "generic/069 generic/070 generic/071 generic/074 generic/080 generic/084 "
    "generic/086 generic/091 generic/095 generic/098 generic/100 generic/109 "
    "generic/113 generic/117 generic/124 generic/132 generic/133 generic/135 "
    "generic/141 generic/169 generic/198 generic/207 generic/208 generic/210 "
    "generic/212 generic/214 generic/215 generic/221 generic/228 generic/241 "
    "generic/246 generic/247 generic/248 generic/249 generic/257 generic/258 "
    "generic/286 generic/308 generic/310 generic/313 generic/315 generic/339 "
    "generic/340 generic/344 generic/345 generic/354 generic/360 generic/391 "
    "generic/393 generic/394 generic/406 generic/412 generic/422 generic/428 "
    "generic/432 generic/433 generic/437 generic/443 generic/450 generic/451 "
    "generic/452 generic/460 generic/464 generic/465 generic/528 generic/538 "
    "generic/565 generic/568 generic/590 generic/591 generic/599 generic/604 "
    "generic/609 generic/615 generic/632 generic/634 generic/635 generic/637 "
    "generic/638 generic/639"
)

# =============================================================================
# Section: Global Options
# =============================================================================

# Standard xfstests mount points (used by all tests)
_scratch_folder = "/mnt/scratch"
_test_folder = "/mnt/test"

# -----------------------------------------------------------------------------
# Parallel Worker Configuration
# -----------------------------------------------------------------------------
# Number of parallel workers for Azure File Share (verify_azure_file_share) test.
#
# SCOPE: This variable ONLY affects the verify_azure_file_share test case.
#        All other test cases (data disk, NVMe) use sequential execution
#        via _execute_xfstests() and are completely unaffected.
#
# The after_case() method references this for cleanup, but uses defensive
# try/except blocks that fail silently for non-parallel tests.
#
# RECOMMENDED VALUES:
#   - 3 workers: ~24 min runtime, good balance of speed vs resource usage
#   - 4 workers: ~18-20 min runtime, better parallelization
#   - Higher values: Diminishing returns, more Azure resources consumed
#
# RESOURCE IMPACT (per worker):
#   - 1 xfstests directory copy (~500MB on remote VM)
#   - 2 Azure File Shares (test + scratch)
#   - 2 mount points on VM
#
# LOAD BALANCING NOTE:
#   Tests are distributed round-robin by count, not by runtime.
#   Some tests vary significantly in duration (0s to 285s), causing
#   potential worker imbalance. Future enhancement: runtime-aware distribution.
_default_worker_count = 4


# =============================================================================
# Azure File Share Parallel Execution Context
# =============================================================================
@dataclass
class AzureFileShareParallelContext:
    """
    Holds state for Azure File Share parallel test execution.

    This dataclass encapsulates all the resources created during parallel
    test setup, making cleanup deterministic and self-documenting. It's
    populated by _setup_azure_file_share_workers() and consumed by
    _cleanup_azure_file_share_workers().

    Usage:
        context = AzureFileShareParallelContext(runner=runner)
        # ... setup populates context fields ...
        # ... tests run ...
        # ... cleanup uses context to know what to clean ...

    Attributes:
        runner: XfstestsParallelRunner managing worker lifecycle
        share_names: Mapping of worker share keys to Azure share names
                     e.g., {"test_1": "lisaXXXw1fs", "scratch_1": "lisaXXXw1sc"}
        all_share_names: Flat list of all created share names for bulk deletion
        fs_url_dict: Mapping of share names to //server/share URLs
        mount_opts: CIFS mount options string used for all mounts
        test_failed: Whether the test failed (affects cleanup behavior)
    """

    runner: XfstestsParallelRunner
    share_names: Dict[str, str] = field(default_factory=dict)
    all_share_names: List[str] = field(default_factory=list)
    fs_url_dict: Dict[str, str] = field(default_factory=dict)
    mount_opts: str = ""
    test_failed: bool = False


def _prepare_data_disk(
    node: Node,
    disk_name: str,
    disk_mount: Dict[str, str],
    file_system: FileSystem = FileSystem.xfs,
) -> None:
    mount = node.tools[Mount]
    parted = node.tools[Parted]
    mkfs = node.tools[Mkfs]

    for disk, mount_point in disk_mount.items():
        mount.umount(disk, mount_point)

    parted.make_label(disk_name)
    parted.make_partition(disk_name, "primary", "1", "50%")
    node.execute("sync")
    parted.make_partition(disk_name, "secondary", "50%", "100%")
    node.execute("sync")

    for disk, mount_point in disk_mount.items():
        mkfs.format_disk(disk, file_system)
        node.execute(f"mkdir {mount_point}", sudo=True)


# Updates as of December 2025.
# Default to Provisioned v2 (PV2) billing model for file share creation.
# PV2 allows independent provisioning of storage, IOPS, and throughput.
# PV2 supports smaller minimum quota (32 GiB vs 100 GiB for PV1).
# PV1 fallback is available via use_pv1_model=True for regions without PV2.
# SMB multi channel is enabled by default with premium SKUs.
def _deploy_azure_file_share(
    node: Node,
    environment: Environment,
    names: Dict[str, str],
    azure_file_share: Union[AzureFileShare, Nfs],
    allow_shared_key_access: bool = True,
    enable_private_endpoint: bool = True,
    storage_account_sku: str = "PremiumV2_LRS",
    storage_account_kind: str = "FileStorage",
    file_share_quota_in_gb: int = 32,
    provisioned_iops: Optional[int] = None,
    provisioned_bandwidth_mibps: Optional[int] = None,
    use_pv1_model: bool = False,
) -> Dict[str, str]:
    """
    About: This method will provision azure file shares on a new or existing
    storage account using the Provisioned v2 (PV2) billing model by default.

    PV2 Billing Model (default):
        - SKU: PremiumV2_LRS (SSD) or StandardV2_LRS (HDD)
        - Minimum quota: 32 GiB
        - Independent IOPS/throughput provisioning
        - More cost-effective for testing workloads

    PV1 Billing Model (legacy, use_pv1_model=True):
        - SKU: Premium_LRS (SSD)
        - Minimum quota: 100 GiB
        - IOPS/throughput computed from storage size
        - Use for regions where PV2 is not available

    Args:
        provisioned_iops: Optional IOPS for PV2 (None = use Azure defaults)
        provisioned_bandwidth_mibps: Optional throughput for PV2 (None = defaults)
        use_pv1_model: Set True to use legacy PV1 billing model

    Returns: Dict[str, str] - A dictionary containing the file share names
    and their respective URLs.
    """
    # Handle PV1 fallback - override SKU and quota for compatibility
    if use_pv1_model:
        storage_account_sku = "Premium_LRS"
        file_share_quota_in_gb = max(file_share_quota_in_gb, 100)  # PV1 minimum
        provisioned_iops = None  # PV1 doesn't support explicit IOPS
        provisioned_bandwidth_mibps = None  # PV1 doesn't support explicit throughput
    if isinstance(azure_file_share, AzureFileShare):
        fs_url_dict: Dict[str, str] = azure_file_share.create_file_share(
            file_share_names=list(names.values()),
            environment=environment,
            sku=storage_account_sku,
            kind=storage_account_kind,
            allow_shared_key_access=allow_shared_key_access,
            enable_private_endpoint=enable_private_endpoint,
            quota_in_gb=file_share_quota_in_gb,
            provisioned_iops=provisioned_iops,
            provisioned_bandwidth_mibps=provisioned_bandwidth_mibps,
        )
        test_folders_share_dict: Dict[str, str] = {}
        for key, value in names.items():
            test_folders_share_dict[key] = fs_url_dict[value]
        azure_file_share.create_fileshare_folders(test_folders_share_dict)
    elif isinstance(azure_file_share, Nfs):
        # NFS yet to be implemented
        raise SkippedException("Skipping NFS deployment. Pending implementation.")
    else:
        raise LisaException(f"Unsupported file share type: {type(azure_file_share)}")
    return fs_url_dict


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
    TIME_OUT = 14400  # 4 hours
    # TODO: will include btrfs/244 once the kernel contains below fix.
    # exclude btrfs/244 temporarily for below commit not picked up by distro vendor.
    # https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/commit/fs/btrfs/volumes.c?id=e4571b8c5e9ffa1e85c0c671995bd4dcc5c75091 # noqa: E501
    # TODO: will include ext4/054 once the kernel contains below fix.
    # This is a regression test for three kernel commit:
    # 1. 0f2f87d51aebc (ext4: prevent partial update of the extent blocks)
    # 2. 9c6e071913792 (ext4: check for inconsistent extents between index
    #    and leaf block)
    # 3. 8dd27fecede55 (ext4: check for out-of-order index extents in
    #    ext4_valid_extent_entries())
    # TODO: will include ext4/058 once the kernel contains below fix.
    # Regression test for commit a08f789d2ab5 ext4: fix bug_on ext4_mb_use_inode_pa
    # TODO: will include ext4/059 once the kernel contains below fix.
    # A regression test for b55c3cd102a6 ("ext4: add reserved GDT blocks check")
    # xfs/081 case will hung for long time
    # a1de97fe296c ("xfs: Fix the free logic of state in xfs_attr_node_hasname")
    # ext4/056 will trigger OOPS, reboot the VM, miss below kernel patch
    # commit b1489186cc8391e0c1e342f9fbc3eedf6b944c61
    # ext4: add check to prevent attempting to resize an fs with sparse_super2
    # VM will hung during running case xfs/520
    # commit d0c7feaf8767 ("xfs: add agf freeblocks verify in xfs_agf_verify")
    # generic/738 case might cause hang more than 4 hours on old kernel
    # TODO: will figure out the detailed reason of every excluded case.
    # exclude generic/680 for security reason.
    excluded_tests = (
        "generic/211 generic/430 generic/431 generic/434 generic/738 xfs/438 xfs/490"
        + " btrfs/007 btrfs/178 btrfs/244 btrfs/262"
        + " xfs/030 xfs/032 xfs/050 xfs/052 xfs/106 xfs/107 xfs/122 xfs/132 xfs/138"
        + " xfs/144 xfs/148 xfs/175 xfs/191-input-validation xfs/289 xfs/293 xfs/424"
        + " xfs/432 xfs/500 xfs/508 xfs/512 xfs/514 xfs/515 xfs/516 xfs/518 xfs/521"
        + " xfs/528 xfs/544 ext4/054 ext4/056 ext4/058 ext4/059 xfs/081 xfs/520"
        + " generic/680"
    )

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        if isinstance(node.os, Oracle) and (node.os.information.version <= "9.0.0"):
            self.excluded_tests = self.excluded_tests + " btrfs/299"

    @TestCaseMetadata(
        description="""
        This test case will run generic xfstests testing against
         standard data disk with xfs type system.
        """,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.StandardHDDLRS,
                os_disk_type=schema.DiskType.StandardHDDLRS,
                data_disk_iops=500,
                data_disk_count=search_space.IntRange(min=1),
            ),
            unsupported_os=[BSD, Windows],
        ),
        timeout=TIME_OUT,
        use_new_environment=True,
        priority=3,
    )
    def verify_generic_standard_datadisk(
        self, log_path: Path, result: TestResult
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        node = cast(RemoteNode, environment.nodes[0])
        xfstests = self._install_xfstests(node)
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        suffix = self._get_partition_suffix(data_disks[0])
        self._execute_xfstests(
            log_path,
            xfstests,
            result,
            data_disks[0],
            f"{data_disks[0]}{suffix}1",
            f"{data_disks[0]}{suffix}2",
            excluded_tests=self.excluded_tests,
        )

    @TestCaseMetadata(
        description="""
        This test case will run generic xfstests testing against
         standard data disk with ext4 type system.
        """,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.StandardHDDLRS,
                os_disk_type=schema.DiskType.StandardHDDLRS,
                data_disk_iops=500,
                data_disk_count=search_space.IntRange(min=1),
            ),
            unsupported_os=[BSD, Windows],
        ),
        timeout=TIME_OUT,
        use_new_environment=True,
        priority=3,
    )
    def verify_generic_ext4_standard_datadisk(
        self, log_path: Path, result: TestResult
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        node = cast(RemoteNode, environment.nodes[0])
        xfstests = self._install_xfstests(node)
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        suffix = self._get_partition_suffix(data_disks[0])
        self._execute_xfstests(
            log_path,
            xfstests,
            result,
            data_disks[0],
            f"{data_disks[0]}{suffix}1",
            f"{data_disks[0]}{suffix}2",
            file_system=FileSystem.ext4,
            excluded_tests=self.excluded_tests,
        )

    @TestCaseMetadata(
        description="""
        This test case will run xfs xfstests testing against
         standard data disk with xfs type system.
        """,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.StandardHDDLRS,
                os_disk_type=schema.DiskType.StandardHDDLRS,
                data_disk_iops=500,
                data_disk_count=search_space.IntRange(min=1),
            ),
            unsupported_os=[BSD, Windows],
        ),
        timeout=TIME_OUT,
        use_new_environment=True,
        priority=3,
    )
    def verify_xfs_standard_datadisk(self, log_path: Path, result: TestResult) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        node = cast(RemoteNode, environment.nodes[0])
        xfstests = self._install_xfstests(node)
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        suffix = self._get_partition_suffix(data_disks[0])
        self._execute_xfstests(
            log_path,
            xfstests,
            result,
            data_disks[0],
            f"{data_disks[0]}{suffix}1",
            f"{data_disks[0]}{suffix}2",
            test_type=f"{FileSystem.xfs.name}/quick",
            excluded_tests=self.excluded_tests,
        )

    @TestCaseMetadata(
        description="""
        This test case will run ext4 xfstests testing against
        standard data disk with ext4 type system.
        """,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.StandardHDDLRS,
                os_disk_type=schema.DiskType.StandardHDDLRS,
                data_disk_iops=500,
                data_disk_count=search_space.IntRange(min=1),
            ),
            unsupported_os=[BSD, Windows],
        ),
        timeout=TIME_OUT,
        use_new_environment=True,
        priority=3,
    )
    def verify_ext4_standard_datadisk(self, log_path: Path, result: TestResult) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        node = cast(RemoteNode, environment.nodes[0])
        xfstests = self._install_xfstests(node)
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        suffix = self._get_partition_suffix(data_disks[0])
        self._execute_xfstests(
            log_path,
            xfstests,
            result,
            data_disks[0],
            f"{data_disks[0]}{suffix}1",
            f"{data_disks[0]}{suffix}2",
            file_system=FileSystem.ext4,
            test_type=f"{FileSystem.ext4.name}/quick",
            excluded_tests=self.excluded_tests,
        )

    @TestCaseMetadata(
        description="""
        This test case will run btrfs xfstests testing against
         standard data disk with btrfs type system.
        """,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.StandardHDDLRS,
                os_disk_type=schema.DiskType.StandardHDDLRS,
                data_disk_iops=500,
                data_disk_count=search_space.IntRange(min=1),
            ),
            unsupported_os=[BSD, Windows],
        ),
        timeout=TIME_OUT,
        use_new_environment=True,
        priority=3,
    )
    def verify_btrfs_standard_datadisk(
        self, log_path: Path, result: TestResult
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        node = cast(RemoteNode, environment.nodes[0])
        self._check_btrfs_supported(node)
        xfstests = self._install_xfstests(node)
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        suffix = self._get_partition_suffix(data_disks[0])
        self._execute_xfstests(
            log_path,
            xfstests,
            result,
            data_disks[0],
            f"{data_disks[0]}{suffix}1",
            f"{data_disks[0]}{suffix}2",
            file_system=FileSystem.btrfs,
            test_type=f"{FileSystem.btrfs.name}/quick",
            excluded_tests=self.excluded_tests,
        )

    @TestCaseMetadata(
        description="""
        This test case will run generic xfstests testing against
         nvme data disk with xfs type system.
        """,
        timeout=TIME_OUT,
        priority=3,
        use_new_environment=True,
        requirement=simple_requirement(
            supported_features=[Nvme], unsupported_os=[BSD, Windows]
        ),
    )
    def verify_generic_nvme_datadisk(self, log_path: Path, result: TestResult) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        node = cast(RemoteNode, environment.nodes[0])
        xfstests = self._install_xfstests(node)
        nvme_disk = node.features[Nvme]
        nvme_data_disks = nvme_disk.get_raw_data_disks()
        self._execute_xfstests(
            log_path,
            xfstests,
            result,
            nvme_data_disks[0],
            f"{nvme_data_disks[0]}p1",
            f"{nvme_data_disks[0]}p2",
            excluded_tests=self.excluded_tests,
        )

    @TestCaseMetadata(
        description="""
        This test case will run generic xfstests testing against
         nvme data disk with ext4 type system.
        """,
        timeout=TIME_OUT,
        priority=3,
        use_new_environment=True,
        requirement=simple_requirement(
            supported_features=[Nvme], unsupported_os=[BSD, Windows]
        ),
    )
    def verify_generic_ext4_nvme_datadisk(
        self, log_path: Path, result: TestResult
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        node = cast(RemoteNode, environment.nodes[0])
        xfstests = self._install_xfstests(node)
        nvme_disk = node.features[Nvme]
        nvme_data_disks = nvme_disk.get_raw_data_disks()
        self._execute_xfstests(
            log_path,
            xfstests,
            result,
            nvme_data_disks[0],
            f"{nvme_data_disks[0]}p1",
            f"{nvme_data_disks[0]}p2",
            file_system=FileSystem.ext4,
            excluded_tests=self.excluded_tests,
        )

    @TestCaseMetadata(
        description="""
        This test case will run xfs xfstests testing against
         nvme data disk with xfs type system.
        """,
        timeout=TIME_OUT,
        priority=3,
        use_new_environment=True,
        requirement=simple_requirement(
            supported_features=[Nvme], unsupported_os=[BSD, Windows]
        ),
    )
    def verify_xfs_nvme_datadisk(self, log_path: Path, result: TestResult) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        node = cast(RemoteNode, environment.nodes[0])
        xfstests = self._install_xfstests(node)
        nvme_disk = node.features[Nvme]
        nvme_data_disks = nvme_disk.get_raw_data_disks()
        self._execute_xfstests(
            log_path,
            xfstests,
            result,
            nvme_data_disks[0],
            f"{nvme_data_disks[0]}p1",
            f"{nvme_data_disks[0]}p2",
            test_type=f"{FileSystem.xfs.name}/quick",
            excluded_tests=self.excluded_tests,
        )

    @TestCaseMetadata(
        description="""
        This test case will run ext4 xfstests testing against
         nvme data disk with ext4 type system.
        """,
        timeout=TIME_OUT,
        priority=3,
        use_new_environment=True,
        requirement=simple_requirement(
            supported_features=[Nvme], unsupported_os=[BSD, Windows]
        ),
    )
    def verify_ext4_nvme_datadisk(self, log_path: Path, result: TestResult) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        node = cast(RemoteNode, environment.nodes[0])
        xfstests = self._install_xfstests(node)
        nvme_disk = node.features[Nvme]
        nvme_data_disks = nvme_disk.get_raw_data_disks()
        self._execute_xfstests(
            log_path,
            xfstests,
            result,
            nvme_data_disks[0],
            f"{nvme_data_disks[0]}p1",
            f"{nvme_data_disks[0]}p2",
            file_system=FileSystem.ext4,
            test_type=f"{FileSystem.ext4.name}/quick",
            excluded_tests=self.excluded_tests,
        )

    @TestCaseMetadata(
        description="""
        This test case will run btrfs xfstests testing against
         nvme data disk with btrfs type system.
        """,
        timeout=TIME_OUT,
        priority=3,
        use_new_environment=True,
        requirement=simple_requirement(
            supported_features=[Nvme], unsupported_os=[BSD, Windows]
        ),
    )
    def verify_btrfs_nvme_datadisk(self, log_path: Path, result: TestResult) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        node = cast(RemoteNode, environment.nodes[0])
        self._check_btrfs_supported(node)
        xfstests = self._install_xfstests(node)
        nvme_disk = node.features[Nvme]
        nvme_data_disks = nvme_disk.get_raw_data_disks()
        self._execute_xfstests(
            log_path,
            xfstests,
            result,
            nvme_data_disks[0],
            f"{nvme_data_disks[0]}p1",
            f"{nvme_data_disks[0]}p2",
            file_system=FileSystem.btrfs,
            test_type=f"{FileSystem.btrfs.name}/quick",
            excluded_tests=self.excluded_tests,
        )

    def _setup_azure_file_share_workers(
        self,
        log: Logger,
        node: RemoteNode,
        xfstests: Xfstests,
        environment: Environment,
        azure_file_share: AzureFileShare,
        runner: XfstestsParallelRunner,
        random_str: str,
    ) -> AzureFileShareParallelContext:
        """
        Set up Azure File Shares for parallel xfstests workers.

        Creates separate file shares per worker and configures each worker's
        local.config and exclude.txt. Worker directories must be created
        by runner.create_workers() before calling this method.

        Azure File Share Requirements:
        - Each worker needs its own test + scratch share (CIFS doesn't support
          subdirectory mounts for xfstests)
        - Share names follow pattern: lisa{random}w{id}fs / lisa{random}w{id}sc

        Args:
            log: Logger for status messages
            node: Remote VM node to configure
            xfstests: Xfstests tool instance
            environment: LISA environment for Azure provisioning
            azure_file_share: AzureFileShare feature for share creation
            runner: XfstestsParallelRunner with workers already created
            random_str: Random string for unique share naming

        Returns:
            AzureFileShareParallelContext: Context object with all setup state
        """
        # Initialize context with runner
        ctx = AzureFileShareParallelContext(runner=runner)
        worker_paths = runner.worker_paths

        # Create separate file shares per worker for isolation
        # Each worker gets: test share (w{id}fs) + scratch share (w{id}sc)
        for worker_id in runner.worker_ids():
            test_share = f"lisa{random_str}w{worker_id}fs"
            scratch_share = f"lisa{random_str}w{worker_id}sc"
            ctx.share_names[f"test_{worker_id}"] = test_share
            ctx.share_names[f"scratch_{worker_id}"] = scratch_share
            ctx.all_share_names.extend([test_share, scratch_share])

        # Build mount point to share name mapping for Azure provisioning
        per_share_quota = max(100 // runner.worker_count, 50)
        names_dict: Dict[str, str] = {}
        for worker_id in runner.worker_ids():
            test_mount = f"{_test_folder}_worker_{worker_id}"
            scratch_mount = f"{_scratch_folder}_worker_{worker_id}"
            names_dict[test_mount] = ctx.share_names[f"test_{worker_id}"]
            names_dict[scratch_mount] = ctx.share_names[f"scratch_{worker_id}"]

        log.info(f"Creating {len(ctx.all_share_names)} Azure file shares for workers")
        ctx.fs_url_dict = _deploy_azure_file_share(
            node=node,
            environment=environment,
            names=names_dict,
            azure_file_share=azure_file_share,
            file_share_quota_in_gb=per_share_quota,
            provisioned_bandwidth_mibps=110,
            provisioned_iops=3110,
        )

        ctx.mount_opts = (
            f"-o {_default_smb_mount},"
            f"credentials={azure_file_share.credential_file}"
        )

        # Create worker mount points on the VM
        for worker_id in runner.worker_ids():
            test_mount = f"{_test_folder}_worker_{worker_id}"
            scratch_mount = f"{_scratch_folder}_worker_{worker_id}"
            node.execute(f"mkdir -p {test_mount} {scratch_mount}", sudo=True)

        # Configure each worker's local.config with worker-specific paths
        for worker_id in runner.worker_ids():
            test_mount = f"{_test_folder}_worker_{worker_id}"
            scratch_mount = f"{_scratch_folder}_worker_{worker_id}"
            test_share_name = ctx.share_names[f"test_{worker_id}"]
            scratch_share_name = ctx.share_names[f"scratch_{worker_id}"]
            test_dev = ctx.fs_url_dict[test_share_name]
            scratch_dev = ctx.fs_url_dict[scratch_share_name]
            # worker_paths is 0-indexed, worker_ids are 1-indexed
            worker_path = worker_paths[worker_id - 1]

            log.debug(
                f"Worker {worker_id}: Configuring local.config "
                f"(test_dev={test_dev}, scratch_dev={scratch_dev})"
            )

            xfstests.set_local_config(
                scratch_dev=scratch_dev,
                scratch_mnt=scratch_mount,
                test_dev=test_dev,
                test_folder=test_mount,
                file_system="cifs",
                test_section="cifs",
                mount_opts=ctx.mount_opts,
                testfs_mount_opts=ctx.mount_opts,
                overwrite_config=True,
                xfstests_path=worker_path,
            )

            xfstests.set_excluded_tests(
                _default_smb_excluded_tests,
                xfstests_path=worker_path,
            )

        return ctx

    def _cleanup_azure_file_share_workers(
        self,
        log: Logger,
        node: RemoteNode,
        ctx: AzureFileShareParallelContext,
        azure_file_share: AzureFileShare,
        environment: Environment,
    ) -> None:
        """
        Clean up all resources created for parallel Azure File Share workers.

        Cleanup sequence (in order):
        1. Unmount worker-specific test/scratch directories
        2. Remove worker xfstests directory copies (via runner.cleanup_workers)
        3. Delete Azure file shares (respects keep_environment setting)

        Args:
            log: Logger for status messages
            node: Remote VM node to clean up
            ctx: AzureFileShareParallelContext with all setup state
            azure_file_share: AzureFileShare feature for share deletion
            environment: LISA environment for platform settings
        """
        runner = ctx.runner

        # Step 1: Unmount worker mount points
        log.debug("Cleaning up worker mount points...")
        for worker_id in runner.worker_ids():
            test_mount = f"{_test_folder}_worker_{worker_id}"
            scratch_mount = f"{_scratch_folder}_worker_{worker_id}"
            try:
                node.tools[Mount].umount("", test_mount, erase=False)
                node.tools[Mount].umount("", scratch_mount, erase=False)
            except Exception:
                pass  # Ignore unmount failures (may already be unmounted)

        # Step 2: Remove worker xfstests directory copies
        runner.cleanup_workers()

        # Step 3: Delete Azure file shares (respects keep_environment setting)
        should_cleanup = True
        if environment.platform:
            keep_environment = environment.platform.runbook.keep_environment
            if keep_environment == constants.ENVIRONMENT_KEEP_ALWAYS:
                should_cleanup = False
                log.info(
                    f"Skipping Azure file share cleanup as "
                    f"keep_environment={keep_environment}"
                )
            elif keep_environment == constants.ENVIRONMENT_KEEP_FAILED:
                if ctx.test_failed:
                    should_cleanup = False
                    log.info(
                        f"Skipping Azure file share cleanup as "
                        f"keep_environment={keep_environment} and test failed"
                    )

        if should_cleanup:
            log.info("Cleaning up Azure file shares")
            try:
                azure_file_share.delete_azure_fileshare(ctx.all_share_names)
            except Exception as cleanup_error:
                log.error(f"Failed to clean up Azure file shares: {cleanup_error}")

    @TestCaseMetadata(
        description="""
        This test case will run cifs xfstests testing against
        azure file share.
        The case will provision storage account with private endpoint
        and use access key // ntlmv2 for authentication.

        Parallel Execution:
        Tests are split across multiple workers (default: 3) to reduce
        total execution time. Each worker gets its own:
        - xfstests directory copy (to avoid shared state conflicts)
        - Azure File Share pair (CIFS doesn't support subdirectory mounts)
        - Test and scratch mount points
        """,
        requirement=simple_requirement(
            min_core_count=16,
            supported_platform_type=[AZURE, HYPERV],
            unsupported_os=[BSD, Windows],
        ),
        timeout=TIME_OUT,
        use_new_environment=True,
        priority=5,
    )
    def verify_azure_file_share(
        self, log: Logger, log_path: Path, result: TestResult
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        assert isinstance(environment.platform, AzurePlatform)
        node = cast(RemoteNode, environment.nodes[0])
        if not node.tools[KernelConfig].is_enabled("CONFIG_CIFS"):
            raise UnsupportedDistroException(
                node.os, "current distro is not enabled with cifs module."
            )
        xfstests = self._install_xfstests(node)
        azure_file_share = node.features[AzureFileShare]
        random_str = generate_random_chars(string.ascii_lowercase + string.digits, 10)

        # Create parallel runner for worker management
        runner = XfstestsParallelRunner(
            xfstests=xfstests,
            log=log,
            worker_count=_default_worker_count,
        )
        log.info(f"Using {runner.worker_count} parallel workers for xfstests")

        # Initialize context - will be populated by setup, used by cleanup
        ctx = AzureFileShareParallelContext(runner=runner)

        try:
            # Create worker xfstests directory copies first
            runner.create_workers()

            # Set up Azure file shares and configure workers
            # Returns populated context with all setup state
            ctx = self._setup_azure_file_share_workers(
                log=log,
                node=node,
                xfstests=xfstests,
                environment=environment,
                azure_file_share=azure_file_share,
                runner=runner,
                random_str=random_str,
            )

            # Get the list of tests and split into batches
            all_tests = _default_smb_testcases.split()
            test_batches = runner.split_tests(all_tests)
            log.info(
                f"Split {len(all_tests)} tests into {runner.worker_count} batches: "
                f"{[len(b) for b in test_batches]} tests each"
            )

            log.info("Running xfstests against azure file share with parallel workers")

            # Execute tests in parallel using the runner
            worker_results = runner.run_parallel(
                test_batches=test_batches,
                log_path=log_path,
                result=result,
                test_section="cifs",
                timeout=self.TIME_OUT,
                run_id_prefix="cifs_worker",
            )

            # Aggregate results (raises on failure)
            _, _, ctx.test_failed = runner.aggregate_results(worker_results)

        except Exception:
            ctx.test_failed = True
            raise
        finally:
            self._cleanup_azure_file_share_workers(
                log=log,
                node=node,
                ctx=ctx,
                azure_file_share=azure_file_share,
                environment=environment,
            )

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        """
        Cleanup handler executed after each test case in this test suite.

        This method handles cleanup for BOTH sequential tests (data disk, NVMe)
        AND parallel tests (verify_azure_file_share). The design ensures backward
        compatibility with existing tests while properly cleaning up parallel
        execution resources.

        Cleanup Operations:
        -------------------
        1. Device mapper cleanup: Removes delay-test, huge-test devices
        2. Standard mount points: Unmounts /mnt/scratch, /mnt/test
        3. Worker mount points: Unmounts /mnt/test_worker_N, /mnt/scratch_worker_N
           (best-effort, wrapped in try/except for non-parallel tests)
        4. Worker directories: Removes /tmp/xfs_worker_N directories
           (best-effort, wrapped in try/except for non-parallel tests)
        5. fstab cleanup: Removes entries for test/scratch mount points

        Impact on Non-Parallel Tests:
        -----------------------------
        The worker cleanup loops (steps 3-4) reference _default_worker_count but
        are completely safe for non-parallel tests because:
        - umount on non-existent mount points is caught and ignored
        - cleanup_worker_copy on non-existent directories is caught and ignored
        - This is "defensive cleanup" - attempts that fail are not errors

        This design allows a single after_case() to handle both sequential and
        parallel test cleanup without conditional logic based on test type.
        """
        try:
            node: Node = kwargs.pop("node")
            for path in [
                "/dev/mapper/delay-test",
                "/dev/mapper/huge-test",
                "/dev/mapper/huge-test-zero",
            ]:
                if 0 == node.execute(f"ls -lt {path}", sudo=True).exit_code:
                    node.execute(f"dmsetup remove {path}", sudo=True)

            # Unmount standard mount points (used by all tests)
            for mount_point in [_scratch_folder, _test_folder]:
                node.tools[Mount].umount("", mount_point, erase=False)

            # -------------------------------------------------------------------------
            # Parallel Execution Cleanup (verify_azure_file_share only)
            # -------------------------------------------------------------------------
            # The following cleanup loops attempt to unmount worker-specific mount
            # points and remove worker xfstests directory copies. These resources
            # ONLY exist after running verify_azure_file_share.
            #
            # For all other tests (data disk, NVMe), these loops execute but:
            # - umount fails silently (mount point doesn't exist)
            # - cleanup_worker_copy fails silently (directory doesn't exist)
            #
            # This is intentional "best effort" cleanup that ensures resources are
            # released without requiring test-specific cleanup logic.
            # -------------------------------------------------------------------------

            # Unmount worker-specific mount points (for parallel execution)
            # Uses _default_worker_count to match the number of workers created
            for worker_id in range(1, _default_worker_count + 1):
                for base_mount in [_test_folder, _scratch_folder]:
                    worker_mount = f"{base_mount}_worker_{worker_id}"
                    try:
                        node.tools[Mount].umount("", worker_mount, erase=False)
                    except Exception:
                        pass  # Best effort - resource may not exist

            # Clean up worker xfstests directory copies (for parallel execution)
            # Uses DEFAULT_WORKER_BASE_DIR constant for consistent path generation
            xfstests: Xfstests = node.tools[Xfstests]
            for worker_id in range(1, _default_worker_count + 1):
                try:
                    xfstests.cleanup_worker_copy(
                        worker_id, base_dir=DEFAULT_WORKER_BASE_DIR
                    )
                except Exception:
                    pass  # Best effort - resource may not exist

            # Clean up fstab entries for mount points used by xfstests
            # Use sed to remove specific entries rather than restoring backup
            # This is more reliable and doesn't risk losing other fstab changes
            node.execute(
                f"sed -i '\\#{_test_folder}#d' /etc/fstab",
                sudo=True,
                shell=True,
            )
            node.execute(
                f"sed -i '\\#{_scratch_folder}#d' /etc/fstab",
                sudo=True,
                shell=True,
            )
        except Exception as e:
            raise BadEnvironmentStateException(f"after case, {e}")

    def _execute_xfstests(
        self,
        log_path: Path,
        xfstests: Xfstests,
        result: TestResult,
        data_disk: str = "",
        test_dev: str = "",
        scratch_dev: str = "",
        file_system: FileSystem = FileSystem.xfs,
        test_type: str = "generic/quick",
        test_cases: str = "",
        excluded_tests: str = "",
        mount_opts: str = "",
        testfs_mount_opts: str = "",
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        node = cast(RemoteNode, environment.nodes[0])
        # test_group is a combination of <file_system>/<test_type>.
        # supported values for test_type are quick, auto, db and more.
        # check tests/*/group.list in xfstests-dev directory after 'make install'
        # Note: you must use correct section name from local.config when using
        # test_group
        # a test group for XFS will fail for a config for ext or btrfs
        test_group: str = ""
        if not test_type or test_type == file_system.name:
            test_group = f"{file_system.name}/quick"
        else:
            test_group = test_type
        # Fix Mariner umask for xfstests
        if isinstance(node.os, CBLMariner):
            echo = node.tools[Echo]
            profile_path = node.get_pure_path("/etc/profile")
            echo.write_to_file("umask 0022\n", profile_path, sudo=True, append=True)
            # Close the current session to apply the umask change on the next login
            node.close()

        # TODO: will include generic/641 once the kernel contains below fix.
        # exclude this case generic/641 temporarily
        # it will trigger oops on RHEL8.3/8.4, VM will reboot
        # lack of commit 5808fecc572391867fcd929662b29c12e6d08d81
        if isinstance(node.os, Redhat) and node.os.information.version >= "8.3.0":
            excluded_tests += " generic/641"

        # prepare data disk when xfstesting target is data disk
        if data_disk:
            _prepare_data_disk(
                node,
                data_disk,
                {test_dev: _test_folder, scratch_dev: _scratch_folder},
                file_system=file_system,
            )
        # We mark test_section as the name of the file system.
        xfstests.set_local_config(
            file_system=file_system.name,
            scratch_dev=scratch_dev,
            scratch_mnt=_scratch_folder,
            test_dev=test_dev,
            test_folder=_test_folder,
            test_section=file_system.name,
            mount_opts=mount_opts,
            testfs_mount_opts=testfs_mount_opts,
            overwrite_config=True,
        )
        xfstests.set_excluded_tests(excluded_tests)
        # Reduce run_test timeout by 30s to let it complete before case Timeout.
        # Set to 30 for safety check to ensure test finishes before LISA times out.
        # We mark test_section as the name of the file system.
        # Test group is a combination of <file_system>/<test_type> generated previously
        # test_cases is a string of test cases separated by space, can be empty.
        # If specified, it will add additional cases to the ones from test_group minus
        # exclusion list.
        xfstests.run_test(
            test_section=file_system.name,
            test_group=test_group,
            log_path=log_path,
            result=result,
            data_disk=data_disk,
            test_cases=test_cases,
            timeout=self.TIME_OUT - 30,
        )

    def _install_xfstests(self, node: Node) -> Xfstests:
        try:
            xfstests: Xfstests = node.tools[Xfstests]
            return xfstests
        except UnsupportedDistroException as e:
            raise SkippedException(e)

    def _check_btrfs_supported(self, node: Node) -> None:
        if not node.tools[KernelConfig].is_enabled("CONFIG_BTRFS_FS"):
            raise SkippedException("Current distro doesn't support btrfs file system.")

    def _get_partition_suffix(self, disk: str) -> str:
        """
        Returns the partition suffix based on the disk type.
        (for partitions like /dev/nvme0n2p1, /dev/nvme0n2p2).
        If it's an NVMe disk, it returns "p"
        (for partitions like /dev/sda1, /dev/sda2)
        If it's a SCSI disk, it returns ""
        """
        if "nvme" in disk:
            return "p"
        else:
            return ""
