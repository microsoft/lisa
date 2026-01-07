# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import string
from functools import partial
from pathlib import Path, PurePath
from typing import Any, Callable, Dict, List, Optional, Union, cast

from microsoft.testsuites.xfstests.xfstests import Xfstests, XfstestsRunResult

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
from lisa.util.parallel import run_in_parallel

# Global variables
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
# Section : Global options
_scratch_folder = "/mnt/scratch"
_test_folder = "/mnt/test"

# Default parallel worker count for Azure File Share tests
_default_worker_count = 3


def _split_tests_into_batches(
    test_list: List[str], num_batches: int
) -> List[List[str]]:
    """
    Split tests into batches using simple round-robin distribution.

    Args:
        test_list: List of test case names (e.g., ["generic/001", "generic/007"])
        num_batches: Number of batches to create

    Returns:
        List of test lists, one per batch
    """
    batches: List[List[str]] = [[] for _ in range(num_batches)]

    for i, test in enumerate(test_list):
        batches[i % num_batches].append(test)

    return batches


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
        worker_count: int,
        random_str: str,
    ) -> tuple[Dict[str, str], List[str], Dict[str, str], List[PurePath], str]:
        """
        Set up Azure File Shares and worker directories for parallel xfstests.

        Creates separate file shares per worker and worker-specific xfstests
        directory copies for isolated parallel execution.

        Returns:
            tuple: (share_names, all_share_names, fs_url_dict, worker_paths, mount_opts)
        """
        # Create separate file shares per worker for isolation
        share_names: Dict[str, str] = {}
        all_share_names: List[str] = []
        for worker_id in range(1, worker_count + 1):
            test_share = f"lisa{random_str}w{worker_id}fs"
            scratch_share = f"lisa{random_str}w{worker_id}sc"
            share_names[f"test_{worker_id}"] = test_share
            share_names[f"scratch_{worker_id}"] = scratch_share
            all_share_names.extend([test_share, scratch_share])

        # Provision file shares for each worker
        per_share_quota = max(100 // worker_count, 50)
        names_dict: Dict[str, str] = {}
        for worker_id in range(1, worker_count + 1):
            test_mount = f"{_test_folder}_worker_{worker_id}"
            scratch_mount = f"{_scratch_folder}_worker_{worker_id}"
            names_dict[test_mount] = share_names[f"test_{worker_id}"]
            names_dict[scratch_mount] = share_names[f"scratch_{worker_id}"]

        log.info(f"Creating {len(all_share_names)} Azure file shares for workers")
        fs_url_dict: Dict[str, str] = _deploy_azure_file_share(
            node=node,
            environment=environment,
            names=names_dict,
            azure_file_share=azure_file_share,
            file_share_quota_in_gb=per_share_quota,
            provisioned_bandwidth_mibps=110,
            provisioned_iops=3110,
        )

        mount_opts = (
            f"-o {_default_smb_mount},"
            f"credentials={azure_file_share.credential_file}"
        )

        # Create worker mount points
        for worker_id in range(1, worker_count + 1):
            test_mount = f"{_test_folder}_worker_{worker_id}"
            scratch_mount = f"{_scratch_folder}_worker_{worker_id}"
            node.execute(f"mkdir -p {test_mount} {scratch_mount}", sudo=True)

        # Create separate xfstests directory copies for each worker
        log.info("Creating worker-specific xfstests directory copies...")
        worker_paths: List[PurePath] = []
        for worker_id in range(1, worker_count + 1):
            log.debug(f"Worker {worker_id}: Creating xfstests directory copy")
            worker_path = xfstests.create_worker_copy(worker_id)
            worker_paths.append(worker_path)
            log.debug(f"Worker {worker_id}: xfstests copy created at {worker_path}")

        # Configure each worker's local.config
        for worker_id in range(1, worker_count + 1):
            test_mount = f"{_test_folder}_worker_{worker_id}"
            scratch_mount = f"{_scratch_folder}_worker_{worker_id}"
            test_share = share_names[f"test_{worker_id}"]
            scratch_share = share_names[f"scratch_{worker_id}"]
            test_dev = fs_url_dict[test_share]
            scratch_dev = fs_url_dict[scratch_share]
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
                mount_opts=mount_opts,
                testfs_mount_opts=mount_opts,
                overwrite_config=True,
                xfstests_path=worker_path,
            )

            xfstests.set_excluded_tests(
                _default_smb_excluded_tests,
                xfstests_path=worker_path,
            )

        return share_names, all_share_names, fs_url_dict, worker_paths, mount_opts

    def _cleanup_azure_file_share_workers(
        self,
        log: Logger,
        node: RemoteNode,
        xfstests: Xfstests,
        azure_file_share: AzureFileShare,
        worker_count: int,
        all_share_names: List[str],
        test_failed: bool,
        environment: Environment,
    ) -> None:
        """Clean up worker mount points, directories, and Azure file shares."""
        # Cleanup worker mount points
        log.debug("Cleaning up worker mount points...")
        for worker_id in range(1, worker_count + 1):
            test_mount = f"{_test_folder}_worker_{worker_id}"
            scratch_mount = f"{_scratch_folder}_worker_{worker_id}"
            try:
                node.tools[Mount].umount("", test_mount, erase=False)
                node.tools[Mount].umount("", scratch_mount, erase=False)
            except Exception:
                pass

        # Cleanup worker xfstests directory copies
        log.debug("Cleaning up worker xfstests directories...")
        for worker_id in range(1, worker_count + 1):
            try:
                xfstests.cleanup_worker_copy(worker_id)
            except Exception:
                pass

        # Respect keep_environment setting for cleanup
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
                if test_failed:
                    should_cleanup = False
                    log.info(
                        f"Skipping Azure file share cleanup as "
                        f"keep_environment={keep_environment} and test failed"
                    )

        if should_cleanup:
            log.info("Cleaning up Azure file shares")
            try:
                azure_file_share.delete_azure_fileshare(all_share_names)
            except Exception as cleanup_error:
                log.warning(f"Failed to clean up Azure file shares: {cleanup_error}")

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

        # Configurable worker count for parallel execution
        worker_count = _default_worker_count
        log.info(f"Using {worker_count} parallel workers for xfstests")

        # Track test failure for keep_environment handling
        test_failed = False
        worker_results: List[XfstestsRunResult] = []
        all_share_names: List[str] = []

        try:
            # Set up workers: file shares, mount points, xfstests copies, configs
            (
                _share_names,
                all_share_names,
                _fs_url_dict,
                worker_paths,
                _mount_opts,
            ) = self._setup_azure_file_share_workers(
                log=log,
                node=node,
                xfstests=xfstests,
                environment=environment,
                azure_file_share=azure_file_share,
                worker_count=worker_count,
                random_str=random_str,
            )

            # Get the list of tests and split into batches using round-robin
            all_tests = _default_smb_testcases.split()
            test_batches = _split_tests_into_batches(all_tests, worker_count)
            log.info(
                f"Split {len(all_tests)} tests into {worker_count} batches: "
                f"{[len(b) for b in test_batches]} tests each"
            )

            log.info("Running xfstests against azure file share with parallel workers")

            # Define worker task function
            def run_worker(
                worker_id: int,
                tests: List[str],
                worker_path: PurePath,
            ) -> XfstestsRunResult:
                """Execute xfstests for a single worker."""
                log.debug(
                    f"Worker {worker_id}: Starting execution of "
                    f"{len(tests)} tests from {worker_path}"
                )
                test_cases_str = " ".join(tests)
                worker_result = xfstests.run_test(
                    test_section="cifs",
                    test_group="",
                    log_path=log_path,
                    result=result,
                    test_cases=test_cases_str,
                    timeout=(self.TIME_OUT - 60) // worker_count + 30,
                    run_id=f"cifs_worker_{worker_id}",
                    raise_on_failure=False,
                    xfstests_path=worker_path,
                )
                log.debug(
                    f"Worker {worker_id}: Completed - "
                    f"{'PASSED' if worker_result.success else 'FAILED'} "
                    f"({worker_result.total_count} tests)"
                )
                return worker_result

            # Create task list for parallel execution
            tasks: List[Callable[[], XfstestsRunResult]] = []
            for worker_id, batch in enumerate(test_batches, start=1):
                if batch:
                    worker_path = worker_paths[worker_id - 1]
                    tasks.append(partial(run_worker, worker_id, batch, worker_path))
                    log.debug(
                        f"Worker {worker_id}: Queued {len(batch)} tests: "
                        f"{batch[:3]}{'...' if len(batch) > 3 else ''}"
                    )

            # Execute all workers in parallel
            log.info(f"Starting {len(tasks)} parallel xfstests workers...")
            worker_results = run_in_parallel(tasks, log=log)
            log.info("All parallel workers completed")

            # Aggregate and log results
            test_failed = self._aggregate_worker_results(log, worker_results)

        except Exception:
            test_failed = True
            raise
        finally:
            self._cleanup_azure_file_share_workers(
                log=log,
                node=node,
                xfstests=xfstests,
                azure_file_share=azure_file_share,
                worker_count=worker_count,
                all_share_names=all_share_names,
                test_failed=test_failed,
                environment=environment,
            )

    def _aggregate_worker_results(
        self, log: Logger, worker_results: List[XfstestsRunResult]
    ) -> bool:
        """
        Aggregate and log results from all workers.

        Returns True if any worker failed, False otherwise.
        Raises LisaException if there are failures.
        """
        total_passed = 0
        total_failed = 0
        test_failed = False

        for worker_result in worker_results:
            if worker_result.success:
                log.info(
                    f"Worker {worker_result.run_id}: PASSED "
                    f"({worker_result.total_count} tests)"
                )
                total_passed += worker_result.total_count
            else:
                log.error(
                    f"Worker {worker_result.run_id}: FAILED "
                    f"({worker_result.fail_count}/{worker_result.total_count} "
                    f"tests failed)"
                )
                total_passed += worker_result.total_count - worker_result.fail_count
                total_failed += worker_result.fail_count
                test_failed = True

        log.info(
            f"Parallel xfstests summary: {total_passed} passed, "
            f"{total_failed} failed across {len(worker_results)} workers"
        )

        # Fail if any worker failed
        failed_results = [r for r in worker_results if not r.success]
        if failed_results:
            total_failures = sum(r.fail_count for r in failed_results)
            total_tests = sum(r.total_count for r in worker_results)
            all_fail_cases = []
            for r in failed_results:
                all_fail_cases.extend(r.fail_cases)
            combined_fail_info = "\n\n".join(
                r.get_failure_message() for r in failed_results
            )
            raise LisaException(
                f"Parallel xfstests failed: {total_failures} of {total_tests} "
                f"tests failed across {len(failed_results)} workers.\n\n"
                f"Failed test cases: {all_fail_cases}\n\n"
                f"Details:\n{combined_fail_info}"
            )

        return test_failed

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        try:
            node: Node = kwargs.pop("node")
            for path in [
                "/dev/mapper/delay-test",
                "/dev/mapper/huge-test",
                "/dev/mapper/huge-test-zero",
            ]:
                if 0 == node.execute(f"ls -lt {path}", sudo=True).exit_code:
                    node.execute(f"dmsetup remove {path}", sudo=True)

            # Unmount standard mount points
            for mount_point in [_scratch_folder, _test_folder]:
                node.tools[Mount].umount("", mount_point, erase=False)

            # Unmount worker-specific mount points (for parallel execution)
            for worker_id in range(1, _default_worker_count + 1):
                for base_mount in [_test_folder, _scratch_folder]:
                    worker_mount = f"{base_mount}_worker_{worker_id}"
                    try:
                        node.tools[Mount].umount("", worker_mount, erase=False)
                    except Exception:
                        pass  # Best effort - may not exist if not parallel test

            # Clean up worker xfstests directory copies (for parallel execution)
            xfstests = node.tools[Xfstests]
            for worker_id in range(1, _default_worker_count + 1):
                try:
                    xfstests.cleanup_worker_copy(worker_id)
                except Exception:
                    pass  # Best effort - may not exist if not parallel test

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
