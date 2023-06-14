# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
import time
from typing import Any, Pattern

from assertpy.assertpy import assert_that

from lisa import (
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.features import Disk, Nfs
from lisa.features.disks import (
    DiskPremiumSSDLRS,
    DiskStandardHDDLRS,
    DiskStandardSSDLRS,
)
from lisa.node import Node
from lisa.operating_system import BSD, Windows
from lisa.schema import DiskType
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.features import AzureDiskOptionSettings
from lisa.sut_orchestrator.azure.tools import Waagent
from lisa.tools import Blkid, Cat, Dmesg, Echo, Lsblk, Mount, NFSClient, Swap, Sysctl
from lisa.tools.blkid import PartitionInfo
from lisa.tools.journalctl import Journalctl
from lisa.util import BadEnvironmentStateException, LisaException, get_matched_str
from lisa.util.perf_timer import create_timer


@TestSuiteMetadata(
    area="storage",
    category="functional",
    description="""
    This test suite is used to run storage related tests.
    """,
)
class Storage(TestSuite):
    DEFAULT_DISK_SIZE_IN_GB = 20
    TIME_OUT = 12000

    # Defaults targetpw
    _uncommented_default_targetpw_regex = re.compile(
        r"(\nDefaults\s+targetpw)|(^Defaults\s+targetpw.*)"
    )

    # kern.cam.da.default_timeout: 300
    _get_default_timeout_bsd_regex = re.compile(
        r"kern.cam.da.default_timeout:\s+(?P<timeout>\d+)\s*"
    )

    os_disk_mount_point = "/"

    @TestCaseMetadata(
        description="""
        This test will check that VM disks are provisioned
        with the correct timeout.
        Steps:
        1. Find the disks for the VM by listing /sys/block/sd*.
        2. Verify the timeout value for disk in
        `/sys/block/<disk>/device/timeout` file is set to 300.
        """,
        priority=2,
        requirement=simple_requirement(supported_platform_type=[AZURE]),
    )
    def verify_disks_device_timeout_setting(
        self,
        node: RemoteNode,
    ) -> None:
        disks = node.features[Disk].get_all_disks()
        root_device_timeout_from_waagent = node.tools[
            Waagent
        ].get_root_device_timeout()  # value in seconds
        for disk in disks:
            timeout = 60
            timer = create_timer()
            while timeout > timer.elapsed(False):
                if isinstance(node.os, BSD):
                    # Extract device type
                    # For example, da0 disk has device type of da
                    matched = re.compile(r"(^[a-z]+)").match(disk)
                    assert matched, f"Failed to extract device type from {disk}"
                    device_type = matched.group(0)

                    # BSD has one setting per device type
                    # and the output is of the format:
                    # kern.cam.da.default_timeout: 300
                    device_timeout_from_distro_unformatted = (
                        node.tools[Sysctl]
                        .run(
                            f"kern.cam.{device_type}.default_timeout",
                            force_run=True,
                            shell=True,
                        )
                        .stdout
                    )
                    device_timeout_from_distro = int(
                        get_matched_str(
                            device_timeout_from_distro_unformatted,
                            self._get_default_timeout_bsd_regex,
                        )
                    )
                else:
                    device_timeout_from_distro = int(
                        node.tools[Cat]
                        .run(f"/sys/block/{disk}/device/timeout", force_run=True)
                        .stdout
                    )
                if root_device_timeout_from_waagent == device_timeout_from_distro:
                    break
                else:
                    time.sleep(1)
            assert_that(
                root_device_timeout_from_waagent,
                f"device {disk} timeout from waagent.conf and distro should match",
            ).is_equal_to(device_timeout_from_distro)

    @TestCaseMetadata(
        description="""
        This test will check that the resource disk is present in the list of mounted
        devices. Most VMs contain a resource disk, which is not a managed disk and
        provides short-term storage for applications and processes. It is intended to
        only store data such as page or swap files.
        Steps:
        1. Get the mount point for the resource disk. If `/var/log/cloud-init.log`
        file is present, mount location is `/mnt`, otherwise it is obtained from
        `ResourceDisk.MountPoint` entry in `waagent.conf` configuration file.
        2. Verify that "/dev/<disk> <mount_point>` entry is present in
        `/etc/mtab` file and the disk should not be equal to os disk.
        """,
        priority=1,
        requirement=simple_requirement(
            disk=AzureDiskOptionSettings(has_resource_disk=True),
            supported_platform_type=[AZURE],
        ),
    )
    def verify_resource_disk_mounted(self, node: RemoteNode) -> None:
        resource_disk_mount_point = node.features[Disk].get_resource_disk_mount_point()
        # os disk(root disk) is the entry with mount point `/' in the output
        # of `mount` command
        os_disk = (
            node.features[Disk]
            .get_partition_with_mount_point(self.os_disk_mount_point)
            .disk
        )
        if isinstance(node.os, BSD):
            partition_info = node.tools[Mount].get_partition_info()
            resource_disk_from_mtab = [
                entry
                for entry in partition_info
                if entry.mount_point == resource_disk_mount_point
            ][0].mount_point
        else:
            mtab = node.tools[Cat].run("/etc/mtab").stdout
            resource_disk_from_mtab = get_matched_str(
                mtab, self._get_mtab_mount_point_regex(resource_disk_mount_point)
            )
        assert (
            resource_disk_from_mtab
        ), f"resource disk mountpoint not found {resource_disk_mount_point}"
        assert_that(
            resource_disk_from_mtab, "Resource disk should not be equal to os disk"
        ).is_not_equal_to(os_disk)

    @TestCaseMetadata(
        description="""
        This test will check that the swap is correctly configured on the VM.
        Steps:
        1. Check if swap file/partition is configured by checking the output of
        `swapon -s` and `lsblk`.
        2. Check swap status in `waagent.conf`.
        3. Verify that truth value in step 1 and step 2 match.
        """,
        priority=1,
        requirement=simple_requirement(supported_platform_type=[AZURE]),
    )
    def verify_swap(self, node: RemoteNode) -> None:
        is_swap_enabled_wa_agent = node.tools[Waagent].is_swap_enabled()
        is_swap_enabled_distro = node.tools[Swap].is_swap_enabled()
        assert_that(
            is_swap_enabled_distro,
            "swap configuration from waagent.conf and distro should match",
        ).is_equal_to(is_swap_enabled_wa_agent)

    @TestCaseMetadata(
        description="""
        This test will check that the file IO operations are working correctly
        Steps:
        1. Get the mount point for the resource disk. If `/var/log/cloud-init.log`
        file is present, mount location is `/mnt`, otherwise it is obtained from
        `ResourceDisk.MountPoint` entry in `waagent.conf` configuration file.
        2. Verify that resource disk is mounted from the output of `mount` command.
        3. Write a text file to the resource disk.
        4. Read the text file and verify that content is same.
        """,
        priority=1,
        requirement=simple_requirement(
            disk=AzureDiskOptionSettings(has_resource_disk=True),
            supported_platform_type=[AZURE],
        ),
    )
    def verify_resource_disk_io(self, node: RemoteNode) -> None:
        resource_disk_mount_point = node.features[Disk].get_resource_disk_mount_point()

        # verify that resource disk is mounted
        # function returns successfully if disk matching mount point is present
        node.features[Disk].get_partition_with_mount_point(resource_disk_mount_point)

        file_path = f"{resource_disk_mount_point}/sample.txt"
        original_text = "Writing to resource disk!!!"

        # write content to the file
        node.tools[Echo].write_to_file(
            original_text, node.get_pure_path(file_path), sudo=True
        )

        # read content from the file
        read_text = node.tools[Cat].read(file_path, force_run=True, sudo=True)

        assert_that(
            read_text,
            "content read from file should be equal to content written to file",
        ).is_equal_to(original_text)

    @TestCaseMetadata(
        description="""
        This test will verify that identifier of root partition matches
        from different sources.

        Steps:
        1. Get the partition identifier from `blkid` command.
        2. Verify that the partition identifier from `blkid` is present in dmesg.
        3. Verify that the partition identifier from `blkid` is present in fstab output.
        """,
        priority=1,
        requirement=simple_requirement(
            supported_platform_type=[AZURE], unsupported_os=[BSD, Windows]
        ),
    )
    def verify_os_partition_identifier(self, log: Logger, node: RemoteNode) -> None:
        # get information of root disk from blkid
        os_partition = (
            node.features[Disk]
            .get_partition_with_mount_point(self.os_disk_mount_point)
            .name
        )
        os_partition_info = node.tools[Blkid].get_partition_info_by_name(os_partition)

        # verify that root=<name> or root=uuid=<uuid> or root=partuuid=<part_uuid> is
        # present in dmesg or journalctl logs
        dmesg = node.tools[Dmesg].run(sudo=True).stdout
        dmesg_root_present = self._check_root_partition_in_log(dmesg, os_partition_info)

        if not dmesg_root_present:
            journalctl_out = node.tools[Journalctl].first_n_logs_from_boot()
            journal_root_present = self._check_root_partition_in_log(
                journalctl_out, os_partition_info
            )
        if not (dmesg_root_present or journal_root_present):
            raise LisaException(
                f"One of root={os_partition_info.name} or "
                f"root=UUID={os_partition_info.uuid} or "
                f"root=PARTUUID={os_partition_info.part_uuid} "
                "should be present in dmesg/journalctl output"
            )

        # verify that "<uuid> /" or "<name> /"or "<part_uuid> /" present in /etc/fstab
        fstab = node.tools[Cat].run("/etc/fstab", sudo=True).stdout
        if (
            not get_matched_str(
                fstab,
                re.compile(
                    rf".*{os_partition_info.name}\s+/",
                ),
            )
            and not get_matched_str(
                fstab,
                re.compile(rf".*UUID={os_partition_info.uuid}\s+/"),
            )
            and not get_matched_str(
                fstab,
                re.compile(rf".*PARTUUID={os_partition_info.part_uuid}\s+/"),
            )
        ):
            raise LisaException(
                f"One of '{os_partition_info.name} /' or "
                "'UUID={os_partition_info.uuid} /' or "
                "'PARTUUID={os_partition_info.part_uuid} /' should be present in fstab"
            )

    @TestCaseMetadata(
        description="""
        This test case will verify that the standard hdd data disks disks can
        be added one after other (serially) while the vm is running.
        Steps:
        1. Get maximum number of data disk for the current vm_size.
        2. Get the number of data disks already added to the vm.
        3. Serially add and remove the data disks and verify that the added
        disks are present in the vm.
        """,
        timeout=TIME_OUT,
        requirement=simple_requirement(disk=DiskStandardHDDLRS()),
    )
    def verify_hot_add_disk_serial(self, log: Logger, node: Node) -> None:
        self._hot_add_disk_serial(
            log, node, DiskType.StandardHDDLRS, self.DEFAULT_DISK_SIZE_IN_GB
        )

    @TestCaseMetadata(
        description="""
        This test case will verify that the standard ssd data disks disks can
        be added serially while the vm is running. The test steps are same as
        `hot_add_disk_serial`.
        """,
        timeout=TIME_OUT,
        requirement=simple_requirement(disk=DiskStandardSSDLRS()),
    )
    def verify_hot_add_disk_serial_standard_ssd(self, log: Logger, node: Node) -> None:
        self._hot_add_disk_serial(
            log, node, DiskType.StandardSSDLRS, self.DEFAULT_DISK_SIZE_IN_GB
        )

    @TestCaseMetadata(
        description="""
        This test case will verify that the premium ssd data disks disks can
        be added serially while the vm is running. The test steps are same as
        `hot_add_disk_serial`.
        """,
        timeout=TIME_OUT,
        requirement=simple_requirement(disk=DiskPremiumSSDLRS()),
    )
    def verify_hot_add_disk_serial_premium_ssd(self, log: Logger, node: Node) -> None:
        self._hot_add_disk_serial(
            log, node, DiskType.PremiumSSDLRS, self.DEFAULT_DISK_SIZE_IN_GB
        )

    @TestCaseMetadata(
        description="""
        This test case will verify that the standard HDD data disks can
        be added in one go (parallel) while the vm is running.
        Steps:
        1. Get maximum number of data disk for the current vm_size.
        2. Get the number of data disks already added to the vm.
        3. Add maximum number of data disks to the VM in parallel.
        4. Verify that the disks are added are available in the OS.
        5. Remove the disks from the vm in parallel.
        6. Verify that the disks are removed from the OS.
        """,
        timeout=TIME_OUT,
        requirement=simple_requirement(disk=DiskStandardHDDLRS()),
    )
    def verify_hot_add_disk_parallel(self, log: Logger, node: Node) -> None:
        self._hot_add_disk_parallel(
            log, node, DiskType.StandardHDDLRS, self.DEFAULT_DISK_SIZE_IN_GB
        )

    @TestCaseMetadata(
        description="""
        This test case will verify that the standard ssd data disks disks can
        be added serially while the vm is running. The test steps are same as
        `hot_add_disk_parallel`.
        """,
        timeout=TIME_OUT,
        requirement=simple_requirement(disk=DiskStandardSSDLRS()),
    )
    def verify_hot_add_disk_parallel_standard_ssd(
        self, log: Logger, node: Node
    ) -> None:
        self._hot_add_disk_parallel(
            log, node, DiskType.StandardSSDLRS, self.DEFAULT_DISK_SIZE_IN_GB
        )

    @TestCaseMetadata(
        description="""
        This test case will verify that the premium ssd data disks disks can
        be added serially while the vm is running. The test steps are same as
        `hot_add_disk_parallel`.
        """,
        timeout=TIME_OUT,
        requirement=simple_requirement(disk=DiskPremiumSSDLRS()),
    )
    def verify_hot_add_disk_parallel_premium_ssd(self, log: Logger, node: Node) -> None:
        self._hot_add_disk_parallel(
            log, node, DiskType.PremiumSSDLRS, self.DEFAULT_DISK_SIZE_IN_GB
        )

    @TestCaseMetadata(
        description="""
        This test case will verify mount azure nfs 4.1 on guest successfully.
        Refer to https://learn.microsoft.com/en-us/azure/storage/files/files-nfs-protocol#features # noqa: E501
        """,
        timeout=TIME_OUT,
        requirement=simple_requirement(supported_features=[Nfs]),
        priority=2,
    )
    def verify_azure_file_share_nfs(self, log: Logger, node: Node) -> None:
        nfs = node.features[Nfs]
        mount_dir = "/mount/azure_share"

        nfs.create_share()
        storage_account_name = nfs.storage_account_name
        mount_nfs = f"{storage_account_name}.file.core.windows.net"
        server_shared_dir = f"{nfs.storage_account_name}/{nfs.file_share_name}"
        try:
            node.tools[NFSClient].setup(
                mount_nfs,
                server_shared_dir,
                mount_dir,
                options="vers=4,minorversion=1,sec=sys",
            )
        except Exception as identifier:
            raise LisaException(
                f"fail to mount {server_shared_dir} into {mount_dir}"
                f"{identifier.__class__.__name__}: {identifier}."
            )
        finally:
            nfs.delete_share()
            node.tools[NFSClient].stop(mount_dir)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        disk = node.features[Disk]

        # cleanup any disks added as part of the test
        # If the cleanup operation fails, mark node to be recycled
        try:
            disk.remove_data_disk()
        except Exception:
            raise BadEnvironmentStateException

    def _hot_add_disk_serial(
        self, log: Logger, node: Node, disk_type: DiskType, size: int
    ) -> None:
        disk = node.features[Disk]
        lsblk = node.tools[Lsblk]

        # get max data disk count for the node
        assert node.capability.disk
        assert isinstance(node.capability.disk.max_data_disk_count, int)
        max_data_disk_count = node.capability.disk.max_data_disk_count
        log.debug(f"max_data_disk_count: {max_data_disk_count}")

        # get the number of data disks already added to the vm
        assert isinstance(node.capability.disk.data_disk_count, int)
        current_data_disk_count = node.capability.disk.data_disk_count
        log.debug(f"current_data_disk_count: {current_data_disk_count}")

        # disks to be added to the vm
        disks_to_add = max_data_disk_count - current_data_disk_count

        # get partition info before adding data disk
        partitions_before_adding_disk = lsblk.get_disks(force_run=True)

        for _ in range(disks_to_add):
            # add data disk
            log.debug("Adding 1 managed disk")
            disks_added = disk.add_data_disk(1, disk_type, size)

            # verify that partition count is increased by 1
            # and the size of partition is correct
            partitons_after_adding_disk = lsblk.get_disks(force_run=True)
            added_partitions = [
                item
                for item in partitons_after_adding_disk
                if item not in partitions_before_adding_disk
            ]
            log.debug(f"added_partitions: {added_partitions}")
            assert_that(added_partitions, "Data disk should be added").is_length(1)
            assert_that(
                added_partitions[0].size_in_gb,
                f"data disk { added_partitions[0].name} size should be equal to "
                f"{size} GB",
            ).is_equal_to(size)

            # remove data disk
            log.debug(f"Removing managed disk: {disks_added}")
            disk.remove_data_disk(disks_added)

            # verify that partition count is decreased by 1
            partition_after_removing_disk = lsblk.get_disks(force_run=True)
            added_partitions = [
                item
                for item in partitions_before_adding_disk
                if item not in partition_after_removing_disk
            ]
            assert_that(added_partitions, "data disks should not be present").is_length(
                0
            )

    def _hot_add_disk_parallel(
        self, log: Logger, node: Node, disk_type: DiskType, size: int
    ) -> None:
        disk = node.features[Disk]
        lsblk = node.tools[Lsblk]

        # get max data disk count for the node
        assert node.capability.disk
        assert isinstance(node.capability.disk.max_data_disk_count, int)
        max_data_disk_count = node.capability.disk.max_data_disk_count
        log.debug(f"max_data_disk_count: {max_data_disk_count}")

        # get the number of data disks already added to the vm
        assert isinstance(node.capability.disk.data_disk_count, int)
        current_data_disk_count = node.capability.disk.data_disk_count
        log.debug(f"current_data_disk_count: {current_data_disk_count}")

        # disks to be added to the vm
        disks_to_add = max_data_disk_count - current_data_disk_count

        # get partition info before adding data disks
        partitions_before_adding_disks = lsblk.get_disks(force_run=True)

        # add data disks
        log.debug(f"Adding {disks_to_add} managed disks")
        disks_added = disk.add_data_disk(disks_to_add, disk_type, size)

        # verify that partition count is increased by disks_to_add
        # and the size of partition is correct
        timeout = 30
        timer = create_timer()
        while timeout > timer.elapsed(False):
            partitons_after_adding_disks = lsblk.get_disks(force_run=True)
            added_partitions = [
                item
                for item in partitons_after_adding_disks
                if item not in partitions_before_adding_disks
            ]
            if len(added_partitions) == disks_to_add:
                break
            else:
                log.debug(f"added disks count: {len(added_partitions)}")
                time.sleep(1)
        assert_that(
            added_partitions, f"{disks_to_add} disks should be added"
        ).is_length(disks_to_add)
        for partition in added_partitions:
            assert_that(
                partition.size_in_gb,
                f"data disk {partition.name} size should be equal to {size} GB",
            ).is_equal_to(size)

        # remove data disks
        log.debug(f"Removing managed disks: {disks_added}")
        disk.remove_data_disk(disks_added)

        # verify that partition count is decreased by disks_to_add
        partition_after_removing_disk = lsblk.get_disks(force_run=True)
        added_partitions = [
            item
            for item in partitions_before_adding_disks
            if item not in partition_after_removing_disk
        ]
        assert_that(added_partitions, "data disks should not be present").is_length(0)

    def _get_managed_disk_id(self, identifier: str) -> str:
        return f"disk_{identifier}"

    def _get_mtab_mount_point_regex(self, mount_point: str) -> Pattern[str]:
        regex = re.compile(rf".*\s+\/dev\/(?P<partition>\D+).*\s+{mount_point}.*")
        return regex

    def _check_root_partition_in_log(
        self, log: str, os_partition_info: PartitionInfo
    ) -> bool:
        if (
            not get_matched_str(
                log,
                re.compile(
                    rf".*BOOT_IMAGE=.*root={os_partition_info.name}",
                ),
            )
            and not get_matched_str(
                log, re.compile(rf".*BOOT_IMAGE=.*root=UUID={os_partition_info.uuid}")
            )
            and not get_matched_str(
                log,
                re.compile(
                    rf".*BOOT_IMAGE=.*root=PARTUUID={os_partition_info.part_uuid}"
                ),
            )
        ):
            return False
        return True
