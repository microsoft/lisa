# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from shlex import quote

from assertpy.assertpy import assert_that

from lisa import (
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.features import SerialConsole
from lisa.operating_system import CentOs, Redhat
from lisa.tools import Reboot, Uname
from lisa.util import SkippedException, TcpConnectionException, constants
from lisa.util.shell import wait_tcp_port_ready


@TestSuiteMetadata(
    area="core",
    category="functional",
    owner="RedHat",
    description="""
    This test suite is to test VM working well after updating on VM and rebooting.
    """,
)
class Boot(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case will
        1. Skip testing if the distro is not redhat/centos type, RHEL added this test
           case, since they encounter an issue which is seeing call trace when boot
           with debug kernel.
        2. Skip if kernel-debug package is not available in repos (e.g. HPC images).
        3. Install kernel-debug and select the newest debug kernel by path,
           independently of GRUB menu ordering. Verify the default before reboot.
        4. Reboot VM, check kernel version is debug type.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[SerialConsole],
            supported_os=[Redhat, CentOs],
        ),
    )
    def verify_boot_with_debug_kernel(
        self, log: Logger, node: RemoteNode, log_path: Path
    ) -> None:
        # Defense-in-depth: catches custom VHD/SIG images whose OS detection
        # may misclassify the node and bypass the supported_os gate.
        if not isinstance(node.os, Redhat) and not isinstance(node.os, CentOs):
            raise SkippedException(
                f"{node.os.name} not supported. "
                "This test case only supports redhat/centos distro."
            )

        # 2. Skip if kernel-debug package is not available (e.g. HPC images
        #    like AlmaLinux HPC intentionally omit debug kernels).
        if not node.os.is_package_in_repo("kernel-debug"):
            raise SkippedException(
                "kernel-debug package is not available in the repo. "
                "This is expected for HPC and minimal images that intentionally "
                "omit debug kernels."
            )

        # Mark the node as dirty as it modifies the boot entry to use a debug kernel.
        # This change may cause subsequent tests to run with the debug kernel,
        # which is not the intended behavior for a kernel validation.
        node.mark_dirty()

        node.os.install_packages(["kernel-debug", "grubby"])
        result = node.execute(
            "ls -1v /boot/vmlinuz-*debug",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Could not list installed debug kernels",
        )
        debug_kernels = result.stdout.splitlines()
        assert_that(
            debug_kernels, "No debug kernel image found after installing kernel-debug."
        ).is_not_empty()
        # Version-sort kernel paths; BLS filenames can sort by different machine IDs.
        debug_kernel = debug_kernels[-1]
        log.info(f"Selecting debug kernel: {debug_kernel}")
        node.execute(
            f"grubby --set-default={quote(debug_kernel)}",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Could not select the debug kernel",
        )
        result = node.execute(
            "grubby --default-kernel",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Could not read the default kernel",
        )
        assert_that(
            result.stdout.strip(),
            "GRUB default does not match the selected debug kernel.",
        ).is_equal_to(debug_kernel)

        # 4. Reboot VM, check kernel version is debug type.
        reboot_tool = node.tools[Reboot]
        reboot_tool.reboot_and_check_panic(log_path)

        is_ready, tcp_error_code = wait_tcp_port_ready(
            node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS],
            node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_PORT],
            log=log,
        )
        if is_ready:
            uname = node.tools[Uname]
            kernel_version = uname.get_linux_information(
                force_run=True
            ).kernel_version_raw
            assert_that(
                kernel_version, "Kernel version is not debug type after reboot."
            ).contains("debug")
        else:
            raise TcpConnectionException(
                node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS],
                node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_PORT],
                tcp_error_code,
                "no panic found in serial log",
            )
