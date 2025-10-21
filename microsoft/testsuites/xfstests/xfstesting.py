# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import string
from pathlib import Path
from typing import Any, Dict, Union, cast

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
from lisa.util import BadEnvironmentStateException, LisaException, generate_random_chars
from microsoft.testsuites.xfstests.xfstests import Xfstests

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
_default_smb_excluded_tests: str = (
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
    "generic/586 generic/589 generic/619 generic/620 generic/640 cifs/001"
)
_default_smb_testcases: str = (
    "generic/001 generic/005 generic/006 generic/007 generic/010 generic/011 "
    "generic/013 generic/014 generic/024 generic/028 generic/029 generic/030 "
    "generic/036 generic/069 generic/070 generic/071 generic/074 generic/080 "
    "generic/084 generic/086 generic/091 generic/095 generic/098 generic/100 "
    "generic/109 generic/113 generic/117 generic/124 generic/125 generic/129 "
    "generic/130 generic/132 generic/133 generic/135 generic/141 generic/169 "
    "generic/184 generic/198 generic/207 generic/208 generic/210 generic/211 "
    "generic/212 generic/214 generic/215 generic/221 generic/228 generic/239 "
    "generic/240 generic/241 generic/246 generic/247 generic/248 generic/249 "
    "generic/257 generic/258 generic/286 generic/306 generic/308 generic/310 "
    "generic/313 generic/315 generic/339 generic/340 generic/344 generic/345 "
    "generic/346 generic/354 generic/360 generic/391 generic/393 generic/394 "
    "generic/406 generic/412 generic/422 generic/428 generic/432 generic/433 "
    "generic/437 generic/443 generic/450 generic/451 generic/452 generic/460 "
    "generic/464 generic/465 generic/469 generic/524 generic/528 generic/538 "
    "generic/565 generic/567 generic/568 generic/590 generic/591 generic/598 "
    "generic/599 generic/604 generic/609 generic/615 generic/632 generic/634 "
    "generic/635 generic/637 generic/638 generic/639"
)
# Section : Global options
_scratch_folder = "/mnt/scratch"
_test_folder = "/mnt/test"


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


# Updates as of march 2025.
# Default premium SKU will be used for file share creation.
# This will ensure SMB multi channel is enabled by default
def _deploy_azure_file_share(
    node: Node,
    environment: Environment,
    names: Dict[str, str],
    azure_file_share: Union[AzureFileShare, Nfs],
    allow_shared_key_access: bool = True,
    enable_private_endpoint: bool = True,
    storage_account_sku: str = "Premium_LRS",
    storage_account_kind: str = "FileStorage",
    file_share_quota_in_gb: int = 100,
) -> Dict[str, str]:
    """
    About: This method will provision azure file shares on a new // existing
    storage account.
    Returns: Dict[str, str] - A dictionary containing the file share names
    and their respective URLs.
    """
    if isinstance(azure_file_share, AzureFileShare):
        fs_url_dict: Dict[str, str] = azure_file_share.create_file_share(
            file_share_names=list(names.values()),
            environment=environment,
            sku=storage_account_sku,
            kind=storage_account_kind,
            allow_shared_key_access=allow_shared_key_access,
            enable_private_endpoint=enable_private_endpoint,
            quota_in_gb=file_share_quota_in_gb,
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

    @TestCaseMetadata(
        description="""
        This test case will run cifs xfstests testing against
        azure file share.
        The case will provision storage account with private endpoint
        and use access key // ntlmv2 for authentication.
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
        file_share_name = f"lisa{random_str}fs"
        scratch_name = f"lisa{random_str}scratch"
        mount_opts = (
            f"-o {_default_smb_mount},"  # noqa: E231
            f"credentials=/etc/smbcredentials/lisa.cred"  # noqa: E231
        )
        fs_url_dict: Dict[str, str] = _deploy_azure_file_share(
            node=node,
            environment=environment,
            names={
                _test_folder: file_share_name,
                _scratch_folder: scratch_name,
            },
            azure_file_share=azure_file_share,
        )
        # Create Xfstest config
        xfstests.set_local_config(
            scratch_dev=fs_url_dict[scratch_name],
            scratch_mnt=_scratch_folder,
            test_dev=fs_url_dict[file_share_name],
            test_folder=_test_folder,
            file_system="cifs",
            test_section="cifs",
            mount_opts=mount_opts,
            testfs_mount_opts=mount_opts,
            overwrite_config=True,
        )
        # Create excluded test file
        xfstests.set_excluded_tests(_default_smb_excluded_tests)
        # run the test
        log.info("Running xfstests against azure file share")
        xfstests.run_test(
            test_section="cifs",
            test_group="cifs/quick",
            log_path=log_path,
            result=result,
            test_cases=_default_smb_testcases,
            timeout=self.TIME_OUT - 30,
        )

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
            for mount_point in [_scratch_folder, _test_folder]:
                node.tools[Mount].umount("", mount_point, erase=False)
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
        # Reduce run_test timeout by 30s to let it complete before case Timeout
        # wait_processes interval in run_test is 10s, set to 30 for safety check
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
            xfstests = node.tools[Xfstests]
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
