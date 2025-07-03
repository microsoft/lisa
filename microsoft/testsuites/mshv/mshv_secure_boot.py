# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from typing import Any, Dict, cast

from lisa import (
    Logger,
    Node,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.features.security_profile import SecureBootEnabled
from lisa.operating_system import CBLMariner
from lisa.sut_orchestrator import AZURE
from lisa.testsuite import simple_requirement
from lisa.tools import Journalctl, Reboot
from lisa.util import (
    SkippedException,
    TcpConnectionException,
    UnsupportedDistroException,
)
from lisa.util.constants import (
    ENVIRONMENTS_NODES_REMOTE_ADDRESS,
    ENVIRONMENTS_NODES_REMOTE_PORT,
)
from lisa.util.shell import wait_tcp_port_ready


@TestSuiteMetadata(
    area="mshv",
    category="functional",
    description="""This test suite covers the secure boot flow for
    Dom0 AzureLinux nodes.
    """,
)
class Dom0SecureBootTestSuite(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        if not isinstance(node.os, CBLMariner):
            raise SkippedException(
                UnsupportedDistroException(
                    node.os, "Dom0 secure boot test supports only Azure Linux."
                )
            )

    @TestCaseMetadata(
        description="""This test verifies secure boot succeeds
        on an Azure Linux Dom0 node.

        Steps:
        1. On first boot, install the Dom0 components
            (e.g. kernel-mshv, mshv, mshv-bootloader-lx, hvloader)
        2. Reboot the VM (The Dom0 components should be loaded)
        3. Await the VM to be ready by checking TCP port connectivity
        4. Verify that secure boot is enabled by checking
            journalctl for "Secure boot enabled"
        5. Verify that the Dom0 stack is **NOT** running by checking
            journalctl for "Hyper-V: running as root partition"
            NOTE: The Dom0 stack is currently not secure boot signed,
            so it will not run in secure boot mode.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[SecureBootEnabled()],
            supported_platform_type=[AZURE],
        ),
    )
    def verify_mshv_secure_boot_succeeds(
        self,
        log: Logger,
        node: RemoteNode,
        log_path: Path,
        variables: Dict[str, Any],
    ) -> None:
        os: CBLMariner = cast(CBLMariner, node.os)

        # 1. Install the Dom0 components
        # Can provide: mshv, mshv-bootloader-lx
        source_mshv_tarball = variables.get("mshv_rpm_tarball")
        if source_mshv_tarball:
            os.add_repository(source_mshv_tarball)

        # Can provide: kernel-mshv, hvloader
        source_base_tarball = variables.get("base_rpm_tarball")
        if source_base_tarball:
            os.add_repository(source_base_tarball)

        components = ["kernel-mshv", "mshv", "mshv-bootloader-lx", "hvloader"]
        os.install_packages(components)

        # 2. Reboot the VM to load the Dom0 components
        reboot_tool = node.tools[Reboot]
        reboot_tool.reboot_and_check_panic(log_path)

        # 3. Await the VM to be ready by checking TCP port connectivity
        is_ready, tcp_error_code = wait_tcp_port_ready(
            node.connection_info[ENVIRONMENTS_NODES_REMOTE_ADDRESS],
            node.connection_info[ENVIRONMENTS_NODES_REMOTE_PORT],
            log=log,
        )

        if is_ready:
            kernel_logs = node.tools[Journalctl].logs_for_kernel()
            # 4. Verify that secure boot is enabled
            # 5. Verify that the Dom0 stack is **NOT** running under secure boot
            assert (
                "Secure boot enabled" in kernel_logs
                and "Hyper-V: running as root partition" not in kernel_logs
            )
        else:
            raise TcpConnectionException(
                node.connection_info[ENVIRONMENTS_NODES_REMOTE_ADDRESS],
                node.connection_info[ENVIRONMENTS_NODES_REMOTE_PORT],
                tcp_error_code,
                "node failed to secure boot after dom0 components installed",
            )
