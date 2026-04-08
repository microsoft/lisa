# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from typing import Any

from assertpy import assert_that

from lisa import (
    Logger,
    RemoteNode,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.environment import EnvironmentStatus
from lisa.features import StartStop
from lisa.sut_orchestrator.openvmm.node import OpenVmmGuestNode
from lisa.tools import Uname


@TestSuiteMetadata(
    area="openvmm",
    category="functional",
    description="""
    This test suite validates OpenVMM guests running on a prepared L1 host.
    """,
)
class OpenVmmPlatform(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        if not isinstance(node, OpenVmmGuestNode):
            raise SkippedException(
                "This suite only applies to OpenVMM guest nodes. "
                f"Actual node type: {type(node).__name__}."
            )

    def _assert_log_path_exists(self, log_path: object) -> None:
        resolved_log_path = Path(str(log_path))
        assert_that(resolved_log_path.exists()).described_as(
            f"log path should exist: {resolved_log_path}"
        ).is_true()

    @TestCaseMetadata(
        description="""
        This case validates that an OpenVMM guest is reachable over SSH and that
        the guest booted successfully.
        """,
        priority=0,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
        ),
    )
    def verify_openvmm_guest_boot(
        self,
        log: Logger,
        node: RemoteNode,
        log_path: Path,
    ) -> None:
        kernel_release = node.tools[Uname].get_linux_information().kernel_version_raw
        log.info(f"Connected to OpenVMM guest kernel {kernel_release}")
        self._assert_log_path_exists(log_path)

    @TestCaseMetadata(
        description="""
        This case validates that platform restart keeps the OpenVMM guest
        reachable and that serial console capture still works after the restart.
        """,
        priority=0,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            supported_features=[StartStop],
        ),
    )
    def verify_openvmm_restart_via_platform(
        self,
        log: Logger,
        node: RemoteNode,
        log_path: Path,
    ) -> None:
        start_stop = node.features[StartStop]
        start_stop.restart()

        kernel_release = node.tools[Uname].get_linux_information().kernel_version_raw
        log.info(f"OpenVMM guest returned after restart on kernel {kernel_release}")
        self._assert_log_path_exists(log_path)

    @TestCaseMetadata(
        description="""
        This case validates that platform stop/start keeps the OpenVMM guest
        reachable for subsequent command execution.
        """,
        priority=0,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            supported_features=[StartStop],
        ),
    )
    def verify_openvmm_stop_start_in_platform(
        self,
        log: Logger,
        node: RemoteNode,
        log_path: Path,
    ) -> None:
        start_stop = node.features[StartStop]
        log.info("Stopping OpenVMM guest via platform")
        start_stop.stop(wait=True)
        log.info("Starting OpenVMM guest via platform")
        start_stop.start(wait=True)

        result = node.execute("echo openvmm-recovered", shell=True)
        result.assert_exit_code()
        assert_that(result.stdout.strip()).described_as(
            "OpenVMM guest should remain reachable over SSH after platform stop/start"
        ).is_equal_to("openvmm-recovered")
        self._assert_log_path_exists(log_path)
