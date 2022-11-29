# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import time
from typing import Optional

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
from lisa.features import Resize, ResizeAction, StartStop
from lisa.schema import NodeSpace
from lisa.tools import Lscpu


@TestSuiteMetadata(
    area="vm_resize",
    category="functional",
    description="""
    This test suite tests vm behavior upon resizing
    """,
)
class VmResize(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case resizes the node and checks if it has the expected capabilities
        (memory size and core count) after the resize

        Steps:
        1. Resize vm into larger vm size
        2. Check the node's core count and memory size against their expected values
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[Resize],
        ),
    )
    def verify_vm_hot_resize(self, log: Logger, node: Node) -> None:
        self._verify_vm_resize(node)

    @TestCaseMetadata(
        description="""
        This test case resizes the node and checks if it has the expected capabilities
        (memory size and core count) after the resize

        Steps:
        1. Resize vm into smaller vm size
        2. Check the node's core count and memory size against their expected values
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[Resize],
        ),
    )
    def verify_vm_hot_resize_decrease(self, log: Logger, node: Node) -> None:
        self._verify_vm_resize(node, ResizeAction.DecreaseCoreCount)

    @TestCaseMetadata(
        description="""
        This test case stops VM resizes the node, starts VM and checks if it has
        the expected capabilities (memory size and core count) after the resize

        Steps:
        1. Resize vm into larger vm size
        2. Check the node's core count and memory size against their expected values
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[Resize, StartStop],
        ),
    )
    def verify_vm_resize_increase(self, node: Node) -> None:
        self._verify_vm_resize(node=node, hot_resize=False)

    @TestCaseMetadata(
        description="""
        This test case stops VM resizes the node, starts VM and checks if it has
        the expected capabilities (memory size and core count) after the resize

        Steps:
        1. Resize vm into smaller vm size
        2. Check the node's core count and memory size against their expected values
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[Resize, StartStop],
        ),
    )
    def verify_vm_resize_decrease(self, node: Node) -> None:
        self._verify_vm_resize(
            node=node, resize_action=ResizeAction.DecreaseCoreCount, hot_resize=False
        )

    def _verify_vm_resize(
        self,
        node: Node,
        resize_action: ResizeAction = ResizeAction.IncreaseCoreCount,
        hot_resize: bool = True,
    ) -> None:
        resize = node.features[Resize]
        if not hot_resize:
            start_stop = node.features[StartStop]
            start_stop.stop()
        retry = 1
        maxretry = 20
        while retry < maxretry:
            try:
                expected_vm_capability: Optional[NodeSpace] = None
                expected_vm_capability = resize.resize(resize_action)
                break
            except Exception as identifier:
                if "no available size for resizing" in str(identifier):
                    raise SkippedException(str(identifier))
                if (
                    "cannot find current vm size in eligible list" in str(identifier)
                    or "OperationNotAllowed" in str(identifier)
                    or "Allocation failed" in str(identifier)
                    or "AllocationFailed" in str(identifier)
                    or "PropertyChangeNotAllowed" in str(identifier)
                    or "cannot boot Hypervisor Generation" in str(identifier)
                    or "due to different CPU Architectures" in str(identifier)
                    or "An existing connection was forcibly closed by the remote host"
                    in str(identifier)
                    or "Following SKUs have failed for Capacity Restrictions"
                    in str(identifier)
                ):
                    retry = retry + 1
                else:
                    raise identifier
                time.sleep(1)
        assert expected_vm_capability, "fail to find proper vm size"
        if not hot_resize:
            start_stop.start()
        self._verify_core_count(node, expected_vm_capability)

    def _verify_core_count(self, node: Node, expected_vm_capability: NodeSpace) -> None:
        lscpu = node.tools[Lscpu]
        actual_core_count = lscpu.get_core_count(force_run=True)
        expected_core_count = expected_vm_capability.core_count
        assert_that(actual_core_count).described_as(
            "The VM resize succeeded but the amount of cores that the vm has is "
            f"incorrect. Expected {expected_core_count} cores but actually had "
            f"{actual_core_count} cores"
        ).is_equal_to(expected_core_count)
