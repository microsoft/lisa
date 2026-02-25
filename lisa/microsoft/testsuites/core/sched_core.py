# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""
Test suite for validating Linux SCHED_CORE (Core Scheduling) functionality.

Core scheduling is a security feature that allows grouping of tasks to share
a physical core. Only tasks in the same group can execute simultaneously on
sibling hyperthreads, mitigating side-channel attacks like MDS/L1TF.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import CBLMariner, Linux
from lisa.sut_orchestrator import AZURE, HYPERV, READY
from lisa.tools import Gcc, Rm
from lisa.tools.kernel_config import KernelConfig
from lisa.util import UnsupportedDistroException


@TestSuiteMetadata(
    area="core",
    category="functional",
    description="""
    Validates SCHED_CORE (Core Scheduling) kernel functionality.
    Requires CONFIG_SCHED_CORE enabled.
    """,
    requirement=simple_requirement(
        supported_platform_type=[AZURE, READY, HYPERV],
        supported_os=[Linux],
    ),
)
class SchedCore(TestSuite):
    _file_name = "sched_core_test"
    _test_data_file_path = (
        Path(os.path.dirname(__file__)) / "test_data" / f"{_file_name}.c"
    )

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        if not isinstance(node.os, CBLMariner) or node.os.information.version < "3.0.0":
            raise SkippedException(
                UnsupportedDistroException(
                    node.os,
                    "SCHED_CORE support is only tested on" " AzureLinux 3.0 and later.",
                )
            )

    @TestCaseMetadata(
        description="""
        Verifies basic SCHED_CORE prctl functionality.

        Steps:
        1. Check CONFIG_SCHED_CORE is enabled
        2. Compile and run a test that creates a core scheduling group
        3. Verify a valid cookie is returned
        """,
        priority=2,
    )
    def verify_sched_core_basic(self, node: Node, log: Logger) -> None:
        kernel_config = node.tools[KernelConfig]
        if not kernel_config.is_enabled("CONFIG_SCHED_CORE"):
            raise SkippedException("CONFIG_SCHED_CORE is not enabled.")

        log.info("CONFIG_SCHED_CORE is enabled")

        node_src = node.working_path / f"{self._file_name}.c"
        node_bin = node.working_path / self._file_name

        try:
            node.shell.copy(
                local_path=self._test_data_file_path,
                node_path=node_src,
            )
            node.tools[Gcc].compile(str(node_src), str(node_bin))

            result = node.execute(str(node_bin), sudo=True)
            log.info(f"Output: {result.stdout}")

            assert_that(result.exit_code).described_as(
                f"SCHED_CORE test failed: {result.stderr}"
            ).is_equal_to(0)

            assert_that(result.stdout).contains("SCHED_CORE OK")

        finally:
            rm = node.tools[Rm]
            rm.remove_file(str(node_src))
            rm.remove_file(str(node_bin))
