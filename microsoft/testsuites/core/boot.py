# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path

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
        2. Install kernel-debug package and set boot with this debug kernel.
        3. Reboot VM, check kernel version is debug type.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[SerialConsole],
        ),
    )
    def verify_boot_with_debug_kernel(
        self, log: Logger, node: RemoteNode, log_path: Path
    ) -> None:
        # 1. Skip testing if the distro is not redhat type.
        if not isinstance(node.os, Redhat) and not isinstance(node.os, CentOs):
            raise SkippedException(
                f"{node.os.name} not supported. "
                "This test case only supports redhat/centos distro."
            )

        # 2. Install kernel-debug package and set boot with this debug kernel.
        node.os.install_packages("kernel-debug")
        result = node.execute("grub2-set-default 0", sudo=True)
        result.assert_exit_code()

        # 3. Reboot VM, check kernel version is debug type.
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
