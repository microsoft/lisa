# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from microsoft.testsuites.cpu.common import verify_cpu_hot_plug


@TestSuiteMetadata(
    area="cpu",
    category="stress",
    description="""
    This test suite is used to run cpu related tests under stress.
    """,
)
class CPUStressSuite(TestSuite):
    @TestCaseMetadata(
        description="""
            This test will check cpu hotplug under stress.
            Detailed steps please refer case verify_cpu_hot_plug.
            """,
        priority=3,
        requirement=simple_requirement(
            min_core_count=32,
        ),
    )
    def stress_cpu_hot_plug(self, log: Logger, node: Node) -> None:
        verify_cpu_hot_plug(log, node, 10)
