# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import pathlib
from typing import Any

from assertpy import assert_that

from lisa import Node, SkippedException, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import CBLMariner, Debian, Linux
from lisa.sut_orchestrator import AZURE, HYPERV
from lisa.testsuite import simple_requirement
from lisa.tools import Gcc
from lisa.util.logger import Logger


@TestSuiteMetadata(
    area="cdrom",
    category="functional",
    description="""
        Tests to check the behavior of the virtual cdrom device in VMs.
    """,
)
class CdromSuite(TestSuite):
    # CD drive status constants from linux uapi
    # see https://github.com/torvalds/linux/blob/master/include/uapi/linux/cdrom.h#L417
    _expected_device_status = (
        "CDS_NO_DISC"  # drive tray is closed, no disk in the drive
    )

    @TestCaseMetadata(
        description="""
            Test to check the installation ISO is unloaded
            after provisioning and rebooting a new VM.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_os=[Linux], supported_platform_type=[AZURE, HYPERV]
        ),
    )
    def verify_cdrom_device_status_code(self, node: Node) -> None:
        # check there's a device to test
        if not node.shell.exists(pathlib.PurePosixPath("/dev/cdrom")):
            raise SkippedException(
                "No /dev/cdrom device was present in this distro/image/vm."
            )
        # reboot to ensure there is no iso in the cd/dvd 'drive'
        node.reboot()

        # collect some paths before we start compiling...
        local_path = pathlib.PurePath(__file__).parent.joinpath("cdstat.c")
        working_path = node.get_working_path()
        node_source_path = working_path.joinpath("cdstat.c")
        node_exec_path = working_path.joinpath("cdstat")

        # copy the tiny c program to the node (cdstat.c)
        node.shell.copy(local_path=local_path, node_path=node_source_path)

        # compile it
        node.tools[Gcc].compile(
            filename=str(node_source_path), output_name=str(node_exec_path)
        )
        assert_that(node.shell.exists(node_exec_path)).described_as(
            "Test bug! The build is broken on this distro. "
            f"Could not find {str(node_exec_path)}"
        ).is_true()

        # and run the test if the device is present.
        result = node.execute(
            cmd=str(node_exec_path),
            shell=True,
            sudo=True,
        )
        output = result.stdout.strip()

        # first check for failure to open the cdrom device
        assert_that(result.exit_code).described_as(
            "Needs Triage: calling "
            "open('/dev/cdrom', O_RDONLY|O_NONBLOCK) failed on this VM."
        ).is_not_equal_to(-1)

        # then check if the exit code was expected and
        # log the output code on failure
        assert_that(result.exit_code).described_as(
            "Bug! /dev/cdrom device status should be "
            f"{self._expected_device_status} after reboot, found {output}."
        ).is_zero()

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        distro = node.os
        # Mariner doesn't ship with many dev tools. Install build tools and headers
        if isinstance(distro, CBLMariner):
            distro.install_packages(["kernel-headers", "binutils-devel", "glibc-devel"])
        # debian ships with headers, no setup needed
        elif isinstance(distro, Debian):
            ...
        # the test _should_ run on anything, skip support for others since this
        # is more of a test for the host than the guest.
        else:
            raise SkippedException("cdrom suite only supports Debian and Mariner")
