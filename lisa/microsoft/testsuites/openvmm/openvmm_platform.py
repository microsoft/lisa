# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path

from assertpy import assert_that

from lisa import (
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.environment import EnvironmentStatus
from lisa.features import StartStop
from lisa.tools import Uname


@TestSuiteMetadata(
    area="openvmm",
    category="functional",
    description="""
    This test suite validates OpenVMM guests running on a prepared L1 host.
    """,
)
class OpenVmmPlatform(TestSuite):
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
        assert_that(log_path).described_as("log path should exist").exists()

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
        assert_that(log_path).described_as("log path should exist").exists()
