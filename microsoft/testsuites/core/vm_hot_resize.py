# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from assertpy import assert_that

from lisa import Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.features.resize import Resize
from lisa.schema import NodeSpace
from lisa.tools import Lscpu


@TestSuiteMetadata(
    area="vm_hot_resize",
    category="functional",
    description="""
    This test suite tests vm behavior upon resizing without shutting down
    """,
)
class VmHotResize(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case resizes the node and checks if it has the expected capabilities
        (memory size and core count) after the resize

        Steps:
        1. Resize vm
        2. Check the node's core count and memory size against their expected values
        """,
        priority=1,
    )
    def verify_vm_hot_resize(self, node: Node) -> None:
        resize = node.features[Resize]
        expected_vm_capability = resize.resize()
        self._verify_core_count(node, expected_vm_capability)

    def _verify_core_count(self, node: Node, expected_vm_capability: NodeSpace) -> None:
        lscpu = node.tools[Lscpu]
        actual_core_count = lscpu.get_core_count()
        expected_core_count = expected_vm_capability.core_count
        assert_that(actual_core_count).described_as(
            "The VM resize succeeded but the amount of cores that the vm has is "
            f"incorrect. Expected {expected_core_count} cores but actually had "
            f"{actual_core_count} cores"
        ).is_equal_to(expected_core_count)
