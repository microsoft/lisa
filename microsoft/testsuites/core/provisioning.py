# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from typing import Optional

from lisa import TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.environment import EnvironmentStatus
from lisa.features import DiskEphemeral, DiskPremiumLRS, SerialConsole
from lisa.node import RemoteNode
from lisa.testsuite import simple_requirement
from lisa.util import LisaException, PassedException, SkippedException
from lisa.util.logger import Logger
from lisa.util.perf_timer import create_timer
from lisa.util.shell import wait_tcp_port_ready


@TestSuiteMetadata(
    area="provisioning",
    category="functional",
    description="""
    This test suite uses to verify if an environment can be provisioned correct or not.

    - The basic smoke test can run on all images to determinate if a image can boot and
    reboot.
    - Other provisioning tests verify if an environment can be provisioned with special
    hardware configurations.
    """,
)
class Provisioning(TestSuite):
    TIME_OUT = 300

    @TestCaseMetadata(
        description="""
        This case verifies whether a node is operating normally.

        Steps,
        1. Connect to TCP port 22. If it's not connectable, failed and check whether
            there is kernel panic.
        2. Connect to SSH port 22, and reboot the node. If there is an error and kernel
            panic, fail the case. If it's not connectable, also fail the case.
        3. If there is another error, but not kernel panic or tcp connection, pass with
            warning.
        4. Otherwise, fully passed.
        """,
        priority=0,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            supported_features=[SerialConsole],
        ),
    )
    def smoke_test(self, case_name: str, log: Logger, node: RemoteNode) -> None:
        self._smoke_test(case_name, log, node)

    @TestCaseMetadata(
        description="""
        This case runs smoke test on a node provisioned with emphemeral disk.
        The test steps are same as `smoke_test`.
        """,
        priority=1,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            supported_features=[SerialConsole, DiskEphemeral],
        ),
    )
    def verify_deployment_provision_ephemeral_managed_disk(
        self, case_name: str, log: Logger, node: RemoteNode
    ) -> None:
        self._smoke_test(case_name, log, node)

    @TestCaseMetadata(
        description="""
        This case runs smoke test on a node provisioned with premium disk.
        The test steps are same as `smoke_test`.
        """,
        priority=1,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            supported_features=[SerialConsole, DiskPremiumLRS],
        ),
    )
    def verify_deployment_provision_premium_disk(
        self, case_name: str, log: Logger, node: RemoteNode
    ) -> None:
        self._smoke_test(case_name, log, node)

    def _smoke_test(self, case_name: str, log: Logger, node: RemoteNode) -> None:
        case_path: Optional[Path] = None

        if not node.is_remote:
            raise SkippedException("smoke test : {case_name} cannot run on local node.")

        is_ready, tcp_error_code = wait_tcp_port_ready(
            node.public_address, node.public_port, log=log, timeout=self.TIME_OUT
        )
        if not is_ready:
            serial_console = node.features[SerialConsole]
            case_path = self._create_case_log_path(case_name)
            serial_console.check_panic(saved_path=case_path, stage="bootup")
            raise LisaException(
                f"Cannot connect to [{node.public_address}:{node.public_port}], "
                f"error code: {tcp_error_code}, no panic found in serial log"
            )

        try:
            timer = create_timer()
            log.info(
                f"SSH port 22 is opened, connecting and rebooting '{node.name}'"
            )
            # In this step, the underlying shell will connect to SSH port.
            # If successful, the node will be reboot.
            # If failed, It distinguishes TCP and SSH errors by error messages.
            node.reboot()
            log.info(f"node '{node.name}' rebooted in {timer}")
        except Exception as identifier:
            if not case_path:
                case_path = self._create_case_log_path(case_name)
            serial_console = node.features[SerialConsole]
            # if there is any panic, fail before partial pass
            serial_console.check_panic(saved_path=case_path, stage="reboot")

            # if node cannot be connected after reboot, it should be failed.
            if isinstance(identifier, LisaException) and str(identifier).startswith(
                "cannot connect to TCP port"
            ):
                raise LisaException(f"after reboot, {identifier}")
            raise PassedException(identifier)
