# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from assertpy import assert_that

from lisa import Node, SkippedException, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.features import StartStop
from lisa.sut_orchestrator.openvmm.node import OpenVmmGuestNode
from lisa.testsuite import simple_requirement


@TestSuiteMetadata(
    area="openvmm",
    category="functional",
    description="""
    Smoke coverage for OpenVMM guest provisioning and platform lifecycle.
    """,
)
class OpenVmmSmokeTestSuite(TestSuite):
    @TestCaseMetadata(
        description="""
        Validate an OpenVMM guest is provisioned, reachable over SSH, and can
        execute a simple command after launch.
        """,
        priority=1,
        requirement=simple_requirement(supported_features=[StartStop]),
    )
    def smoke_test(self, node: Node) -> None:
        openvmm_node = self._get_openvmm_guest(node)

        result = openvmm_node.execute("echo openvmm-smoke", shell=True)

        result.assert_exit_code()
        assert_that(result.stdout.strip()).is_equal_to("openvmm-smoke")

    @TestCaseMetadata(
        description="""
        Validate the OpenVMM StartStop feature can stop and start a guest while
        preserving SSH connectivity for subsequent command execution.
        """,
        priority=1,
        requirement=simple_requirement(supported_features=[StartStop]),
    )
    def verify_stop_start_in_platform(self, node: Node) -> None:
        openvmm_node = self._get_openvmm_guest(node)

        start_stop = openvmm_node.features[StartStop]
        start_stop.stop(wait=True)
        start_stop.start(wait=True)

        result = openvmm_node.execute("echo openvmm-recovered", shell=True)

        result.assert_exit_code()
        assert_that(result.stdout.strip()).is_equal_to("openvmm-recovered")

    def _get_openvmm_guest(self, node: Node) -> OpenVmmGuestNode:
        if not isinstance(node, OpenVmmGuestNode):
            raise SkippedException("This suite only applies to OpenVMM guest nodes.")

        return node
