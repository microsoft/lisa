# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from pathlib import Path

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
from lisa.tools import Find, Reboot, Sed, Uname
from lisa.util import (
    LisaException,
    SkippedException,
    TcpConnectionException,
    find_group_in_lines,
)
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
    __index_pattern = re.compile(r"index=(?P<index>.*)", re.M)

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
        package = "kernel-debug"
        if node.os.is_package_in_repo(package):
            node.os.install_packages(package)
        else:
            raise SkippedException(f"no {package} in distro {node.os.name}")

        node.execute("grub2-mkconfig -o /boot/grub2/grub.cfg", sudo=True)
        node.execute("grub2-mkconfig -o  /boot/efi/EFI/redhat/grub.cfg", sudo=True)
        cmd_result = node.tools[Find].find_files(
            node.get_pure_path("/boot"), "vmlinuz-*debug", sudo=True
        )
        index_result = node.execute(f"grubby --info {cmd_result[0]}", sudo=True)
        matched = find_group_in_lines(index_result.stdout, self.__index_pattern)
        index = matched["index"]

        result = node.execute(f"grub2-set-default {index}", sudo=True)
        result.assert_exit_code()
        kernel_version = self._check_kernel_after_reboot(node, log, log_path)
        if "debug" in kernel_version:
            log.debug(f"kernel version {kernel_version} is debug type after reboot")
            return

        result = node.execute(f"grubby --set-default {cmd_result[0]}", sudo=True)
        result.assert_exit_code()
        kernel_version = self._check_kernel_after_reboot(node, log, log_path)
        if "debug" in kernel_version:
            log.debug(f"kernel version {kernel_version} is debug type after reboot")
            return

        sed = node.tools[Sed]
        sed.substitute(
            regexp="GRUB_DEFAULT=.*",
            replacement=f"GRUB_DEFAULT={index}",
            file="/etc/default/grub",
            sudo=True,
        )
        result = node.execute("grub2-mkconfig -o /boot/grub2/grub.cfg", sudo=True)
        node.execute(f"grubby --info {cmd_result[0]}", sudo=True)
        result.assert_exit_code()
        kernel_version = self._check_kernel_after_reboot(node, log, log_path)
        if "debug" in kernel_version:
            log.debug(f"kernel version {kernel_version} is debug type after reboot")
            return

        raise LisaException(
            f"kernel version {kernel_version} is not debug type after reboot"
        )

    def _check_kernel_after_reboot(
        self, node: RemoteNode, log: Logger, log_path: Path
    ) -> str:
        # Reboot VM, check kernel version is debug type.
        reboot_tool = node.tools[Reboot]
        reboot_tool.reboot_and_check_panic(log_path)

        is_ready, tcp_error_code = wait_tcp_port_ready(
            node.public_address, node.public_port, log=log
        )
        if is_ready:
            uname = node.tools[Uname]
            kernel_version = uname.get_linux_information(
                force_run=True
            ).kernel_version_raw
            return kernel_version
        else:
            raise TcpConnectionException(
                node.public_address,
                node.public_port,
                tcp_error_code,
                "no panic found in serial log",
            )
