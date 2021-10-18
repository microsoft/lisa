# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from pathlib import PurePosixPath
from typing import Pattern

from assertpy.assertpy import assert_that

from lisa import (
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.features import Disk
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.features import AzureDiskOptionSettings
from lisa.sut_orchestrator.azure.tools import Waagent
from lisa.tools import Cat, Echo, Swap
from lisa.util import get_matched_str


@TestSuiteMetadata(
    area="storage",
    category="functional",
    description="""
    This test suite is used to run storage related tests.
    """,
)
class Storage(TestSuite):

    # Defaults targetpw
    _uncommented_default_targetpw_regex = re.compile(
        r"(\nDefaults\s+targetpw)|(^Defaults\s+targetpw.*)"
    )

    @TestCaseMetadata(
        description="""
        This test will check that VM root disk(os disk) is provisioned
        with the correct timeout.
        Steps:
        1. Find the root disk (os disk) for the VM. The root disk
        is the entry with mount point `/' in the output of `mount` command.
        2. Verify the timeout value for root disk in
        `/sys/block/<partition>/device/timeout` file is set to 300.
        """,
        priority=1,
        requirement=simple_requirement(supported_platform_type=[AZURE]),
    )
    def verify_root_device_timeout_setting(
        self,
        node: RemoteNode,
    ) -> None:
        os_disk_mount_point = "/"
        os_disk = (
            node.features[Disk].get_partition_with_mount_point(os_disk_mount_point).disk
        )
        root_device_timeout_from_waagent = node.tools[Waagent].get_root_device_timeout()
        root_device_timeout_from_distro = int(
            node.tools[Cat].run(f"/sys/block/{os_disk}/device/timeout").stdout
        )
        assert_that(
            root_device_timeout_from_waagent,
            "root device timeout from waagent.conf and distro should match",
        ).is_equal_to(root_device_timeout_from_distro)

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
    def verify_resource_disk_mtab_entry(self, log: Logger, node: RemoteNode) -> None:
        resource_disk_mount_point = self._get_resource_disk_mount_point(log, node)
        # os disk(root disk) is the entry with mount point `/' in the output
        # of `mount` command
        os_disk_mount_point = "/"
        os_disk = (
            node.features[Disk].get_partition_with_mount_point(os_disk_mount_point).disk
        )
        mtab = node.tools[Cat].run("/etc/mtab").stdout
        resource_disk_from_mtab = get_matched_str(
            mtab, self._get_mtab_mount_point_regex(resource_disk_mount_point)
        )
        assert resource_disk_from_mtab
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
            "swap cofiguration from waagent.conf and distro should match",
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
    def verify_resource_disk_io(self, log: Logger, node: RemoteNode) -> None:
        resource_disk_mount_point = self._get_resource_disk_mount_point(log, node)

        # verify that resource disk is mounted
        # function returns successfully if disk matching mount point is present
        node.features[Disk].get_partition_with_mount_point(resource_disk_mount_point)

        file_path = f"{resource_disk_mount_point}/sample.txt"
        original_text = "Writing to resource disk!!!"

        # write content to the file
        node.tools[Echo].write_to_file(original_text, file_path, sudo=True)

        # read content from the file
        read_text = node.tools[Cat].read_from_file(file_path, force_run=True, sudo=True)

        assert_that(
            read_text,
            "content read from file should be equal to content written to file",
        ).is_equal_to(original_text)

    @TestCaseMetadata(
        description="""
        This test will verify that `Defaults targetpw` is not enabled in the
        `/etc/sudoers` file.

        If `targetpw` is set, `sudo` will prompt for the
        password of the user specified by the -u option (defaults to root)
        instead of the password of the invoking user when running a command
        or editing a file. More information can be found here :
        https://linux.die.net/man/5/sudoers

        Steps:
        1. Get the content of `/etc/sudoers` file.
        2. Verify that `Defaults targetpw` should be disabled, if present.
        """,
        priority=1,
    )
    def verify_default_targetpw(self, log: Logger, node: RemoteNode) -> None:
        sudoers_out = (
            node.tools[Cat].run("/etc/sudoers", sudo=True, force_run=True).stdout
        )
        matched = self._uncommented_default_targetpw_regex.findall(sudoers_out)
        assert_that(
            matched, "Defaults targetpw should not be enabled in /etc/sudoers"
        ).is_length(0)

    def _get_resource_disk_mount_point(
        self,
        log: Logger,
        node: RemoteNode,
    ) -> str:
        if node.shell.exists(
            PurePosixPath("/var/log/cloud-init.log")
        ) and node.shell.exists(PurePosixPath("/var/lib/cloud/instance")):
            log.debug("Disk handled by cloud-init.")
            mount_point = "/mnt"
        else:
            log.debug("Disk handled by waagent.")
            mount_point = node.tools[Waagent].get_resource_disk_mount_point()
        return mount_point

    def _get_mtab_mount_point_regex(self, mount_point: str) -> Pattern[str]:
        regex = re.compile(rf".*\s+\/dev\/(?P<partition>\D+).*\s+{mount_point}.*")
        return regex
