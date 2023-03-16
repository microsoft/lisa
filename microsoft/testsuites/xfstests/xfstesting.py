# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import string
from pathlib import Path
from typing import Any, Dict, cast

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
from lisa.features import Disk, Nvme
from lisa.operating_system import Redhat
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    check_or_create_storage_account,
    delete_file_share,
    delete_storage_account,
    get_or_create_file_share,
    get_storage_credential,
)
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.testsuite import TestResult
from lisa.tools import Echo, FileSystem, KernelConfig, Mkfs, Mount, Parted
from lisa.util import BadEnvironmentStateException, generate_random_chars
from microsoft.testsuites.xfstests.xfstests import Xfstests

_scratch_folder = "/root/scratch"
_test_folder = "/root/test"


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


def _get_smb_version(node: Node) -> str:
    if node.tools[KernelConfig].is_enabled("CONFIG_CIFS_SMB311"):
        version = "3.1.1"
    else:
        version = "3.0"
    return version


def _prepare_azure_file_share(
    node: Node,
    account_credential: Dict[str, str],
    test_folders_share_dict: Dict[str, str],
    fstab_info: str,
) -> None:
    folder_path = node.get_pure_path("/etc/smbcredentials")
    if node.shell.exists(folder_path):
        node.execute(f"rm -rf {folder_path}", sudo=True)
    node.shell.mkdir(folder_path)
    file_path = node.get_pure_path("/etc/smbcredentials/lisa.cred")
    echo = node.tools[Echo]
    username = account_credential["account_name"]
    password = account_credential["account_key"]
    echo.write_to_file(f"username={username}", file_path, sudo=True, append=True)
    echo.write_to_file(f"password={password}", file_path, sudo=True, append=True)
    node.execute("cp -f /etc/fstab /etc/fstab_cifs", sudo=True)
    for folder_name, share in test_folders_share_dict.items():
        node.execute(f"mkdir {folder_name}", sudo=True)
        echo.write_to_file(
            f"{share} {folder_name} cifs {fstab_info}",
            node.get_pure_path("/etc/fstab"),
            sudo=True,
            append=True,
        )


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
    # TODO: will figure out the detailed reason of every excluded case.
    EXCLUDED_TESTS = (
        "generic/211 generic/430 generic/431 generic/434 /xfs/438 xfs/490"
        + " btrfs/007 btrfs/178 btrfs/244 btrfs/262"
        + " xfs/030 xfs/032 xfs/050 xfs/052 xfs/106 xfs/107 xfs/122 xfs/132 xfs/138"
        + " xfs/144 xfs/148 xfs/175 xfs/191-input-validation xfs/289 xfs/293 xfs/424"
        + " xfs/432 xfs/500 xfs/508 xfs/512 xfs/514 xfs/515 xfs/516 xfs/518 xfs/521"
        + " xfs/528 xfs/544 ext4/054 ext4/056 ext4/058 ext4/059 xfs/081 xfs/520"
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
        use_new_environment=True,
        priority=3,
    )
    def xfstesting_generic_standard_datadisk_validation(
        self, log_path: Path, result: TestResult
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        node = cast(RemoteNode, environment.nodes[0])
        xfstests = self._install_xfstests(node)
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        self._execute_xfstests(
            log_path,
            xfstests,
            result,
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
        use_new_environment=True,
        priority=3,
    )
    def xfstesting_xfs_standard_datadisk_validation(
        self, log_path: Path, result: TestResult
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        node = cast(RemoteNode, environment.nodes[0])
        xfstests = self._install_xfstests(node)
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        self._execute_xfstests(
            log_path,
            xfstests,
            result,
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
        use_new_environment=True,
        priority=3,
    )
    def xfstesting_ext4_standard_datadisk_validation(
        self, log_path: Path, result: TestResult
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        node = cast(RemoteNode, environment.nodes[0])
        xfstests = self._install_xfstests(node)
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        self._execute_xfstests(
            log_path,
            xfstests,
            result,
            data_disks[0],
            f"{data_disks[0]}1",
            f"{data_disks[0]}2",
            file_system=FileSystem.ext4,
            test_type=FileSystem.ext4.name,
            excluded_tests=self.EXCLUDED_TESTS,
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
        use_new_environment=True,
        priority=3,
    )
    def xfstesting_btrfs_standard_datadisk_validation(
        self, log_path: Path, result: TestResult
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        node = cast(RemoteNode, environment.nodes[0])
        self._check_btrfs_supported(node)
        xfstests = self._install_xfstests(node)
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        self._execute_xfstests(
            log_path,
            xfstests,
            result,
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
        use_new_environment=True,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def xfstesting_generic_nvme_datadisk_validation(
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
            excluded_tests=self.EXCLUDED_TESTS,
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
            supported_features=[Nvme],
        ),
    )
    def xfstesting_xfs_nvme_datadisk_validation(
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
            test_type=FileSystem.xfs.name,
            excluded_tests=self.EXCLUDED_TESTS,
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
            supported_features=[Nvme],
        ),
    )
    def xfstesting_ext4_nvme_datadisk_validation(
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
            test_type=FileSystem.ext4.name,
            excluded_tests=self.EXCLUDED_TESTS,
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
            supported_features=[Nvme],
        ),
    )
    def xfstesting_btrfs_nvme_datadisk_validation(
        self, log_path: Path, result: TestResult
    ) -> None:
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
            test_type=FileSystem.btrfs.name,
            excluded_tests=self.EXCLUDED_TESTS,
        )

    @TestCaseMetadata(
        description="""
        This test case will run cifs xfstests testing against
         azure file share.
        """,
        requirement=simple_requirement(
            min_core_count=16,
            supported_platform_type=[AZURE],
        ),
        timeout=TIME_OUT,
        use_new_environment=True,
        priority=3,
    )
    def xfstesting_azure_file_share_validation(
        self, log: Logger, log_path: Path, result: TestResult
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        assert isinstance(environment.platform, AzurePlatform)
        node = cast(RemoteNode, environment.nodes[0])
        if not node.tools[KernelConfig].is_enabled("CONFIG_CIFS"):
            raise UnsupportedDistroException(
                node.os, "current distro not enable cifs module."
            )
        xfstests = self._install_xfstests(node)
        version = _get_smb_version(node)
        fstab_info = (
            f"nofail,vers={version},credentials=/etc/smbcredentials/lisa.cred"
            ",dir_mode=0777,file_mode=0777,serverino"
        )
        mount_opts = (
            f"-o vers={version},credentials=/etc/smbcredentials/lisa.cred"
            ",dir_mode=0777,file_mode=0777,serverino"
        )
        platform = environment.platform
        information = environment.get_information()
        resource_group_name = information["resource_group_name"]
        location = information["location"]
        random_str = generate_random_chars(string.ascii_lowercase + string.digits, 10)
        storage_account_name = f"lisasc{random_str}"
        file_share_name = f"lisa{random_str}fs"
        scratch_name = f"lisa{random_str}scratch"
        fs_url_dict: Dict[str, str] = {file_share_name: "", scratch_name: ""}
        try:
            check_or_create_storage_account(
                credential=platform.credential,
                subscription_id=platform.subscription_id,
                account_name=storage_account_name,
                resource_group_name=resource_group_name,
                location=location,
                log=log,
            )
            for share_name, _ in fs_url_dict.items():
                fs_url_dict[share_name] = get_or_create_file_share(
                    credential=platform.credential,
                    subscription_id=platform.subscription_id,
                    account_name=storage_account_name,
                    file_share_name=share_name,
                    resource_group_name=resource_group_name,
                    log=log,
                )
            account_credential = get_storage_credential(
                credential=platform.credential,
                subscription_id=platform.subscription_id,
                account_name=storage_account_name,
                resource_group_name=resource_group_name,
            )
            _prepare_azure_file_share(
                node,
                account_credential,
                {
                    _test_folder: fs_url_dict[file_share_name],
                    _scratch_folder: fs_url_dict[scratch_name],
                },
                fstab_info,
            )

            self._execute_xfstests(
                log_path,
                xfstests,
                result,
                test_dev=fs_url_dict[file_share_name],
                scratch_dev=fs_url_dict[scratch_name],
                excluded_tests=self.EXCLUDED_TESTS,
                mount_opts=mount_opts,
            )
        finally:
            # clean up resources after testing.
            for share_name in [file_share_name, scratch_name]:
                delete_file_share(
                    credential=platform.credential,
                    subscription_id=platform.subscription_id,
                    account_name=storage_account_name,
                    file_share_name=share_name,
                    resource_group_name=resource_group_name,
                    log=log,
                )
            delete_storage_account(
                credential=platform.credential,
                subscription_id=platform.subscription_id,
                account_name=storage_account_name,
                resource_group_name=resource_group_name,
                log=log,
            )
            # revert file into original status after testing.
            node.execute("cp -f /etc/fstab_cifs /etc/fstab", sudo=True)

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
        except Exception as identifier:
            raise BadEnvironmentStateException(f"after case, {identifier}")

    def _execute_xfstests(
        self,
        log_path: Path,
        xfstests: Xfstests,
        result: TestResult,
        data_disk: str = "",
        test_dev: str = "",
        scratch_dev: str = "",
        file_system: FileSystem = FileSystem.xfs,
        test_type: str = "generic",
        excluded_tests: str = "",
        mount_opts: str = "",
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        node = cast(RemoteNode, environment.nodes[0])
        # TODO: will include generic/641 once the kernel contains below fix.
        # exclude this case generic/641 temporarily
        # it will trigger oops on RHEL8.3/8.4, VM will reboot
        # lack of commit 5808fecc572391867fcd929662b29c12e6d08d81
        if (
            test_type == "generic"
            and isinstance(node.os, Redhat)
            and node.os.information.version >= "8.3.0"
        ):
            excluded_tests += " generic/641"

        # prepare data disk when xfstesting target is data disk
        if data_disk:
            _prepare_data_disk(
                node,
                data_disk,
                {test_dev: _test_folder, scratch_dev: _scratch_folder},
                file_system=file_system,
            )

        xfstests.set_local_config(
            scratch_dev,
            _scratch_folder,
            test_dev,
            _test_folder,
            test_type,
            mount_opts,
        )
        xfstests.set_excluded_tests(excluded_tests)
        xfstests.run_test(test_type, log_path, result, data_disk, self.TIME_OUT)

    def _install_xfstests(self, node: Node) -> Xfstests:
        try:
            xfstests = node.tools[Xfstests]
            return xfstests
        except UnsupportedDistroException as identifier:
            raise SkippedException(identifier)

    def _check_btrfs_supported(self, node: Node) -> None:
        if not node.tools[KernelConfig].is_enabled("CONFIG_BTRFS_FS"):
            raise SkippedException("Current distro doesn't support btrfs file system.")
