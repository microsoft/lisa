# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import time
from typing import Any, Optional, cast

from assertpy import assert_that

from lisa import (
    Node,
    RemoteNode,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.features import Resize, ResizeAction, StartStop
from lisa.schema import NodeSpace
from lisa.testsuite import TestResult
from lisa.tools import Lscpu
from lisa.util.logger import Logger


@TestSuiteMetadata(
    area="vm_resize",
    category="functional",
    description="""
    This test suite tests VM behavior upon resizing
    """,
)
class VmResize(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case hot resizes the VM and checks if it has the expected capabilities
        (memory size and core count) after the hot resize

        Steps:
        1. Resize VM into larger VM size
        2. Check the VM's core count and memory size after hot resize
            against their expected values
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[Resize],
        ),
    )
    def verify_vm_hot_resize(self, result: TestResult) -> None:
        self._verify_vm_resize(
            test_result=result,
        )

    @TestCaseMetadata(
        description="""
        This test case hot resizes the VM and checks if it has the expected capabilities
        (memory size and core count) after the resize

        Steps:
        1. Resize VM into smaller VM size
        2. Check the VM's core count and memory size after hot resize
            against their expected values
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[Resize],
        ),
    )
    def verify_vm_hot_resize_decrease(self, result: TestResult) -> None:
        self._verify_vm_resize(
            test_result=result, resize_action=ResizeAction.DecreaseCoreCount
        )

    @TestCaseMetadata(
        description="""
        This test case stops VM resizes the VM, starts VM and checks if it has
        the expected capabilities (memory size and core count) after the resize

        Steps:
        1. Stop VM
        2. Resize VM into larger VM size
        3. Start VM
        4. Check the VM's core count and memory size against their expected values
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[Resize, StartStop],
        ),
    )
    def verify_vm_resize_increase(self, result: TestResult) -> None:
        self._verify_vm_resize(test_result=result, hot_resize=False)

    @TestCaseMetadata(
        description="""
        This test case stops VM resizes the VM, starts VM and checks if it has
        the expected capabilities (memory size and core count) after the resize

        Steps:
        1. Stop VM
        2. Resize VM into smaller VM size
        3. Start VM
        4. Check the VM's core count and memory size against their expected values
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[Resize, StartStop],
        ),
    )
    def verify_vm_resize_decrease(self, result: TestResult) -> None:
        self._verify_vm_resize(
            test_result=result,
            resize_action=ResizeAction.DecreaseCoreCount,
            hot_resize=False,
        )

    def _verify_vm_resize(
        self,
        test_result: TestResult,
        resize_action: ResizeAction = ResizeAction.IncreaseCoreCount,
        hot_resize: bool = True,
    ) -> None:
        environment = test_result.environment
        assert environment, "fail to get environment from testresult"
        node = cast(RemoteNode, environment.nodes[0])

        resize = node.features[Resize]
        if not hot_resize:
            start_stop = node.features[StartStop]
            start_stop.stop()
        retry = 1
        maxretry = 20
        while retry < maxretry:
            try:
                expected_vm_capability: Optional[NodeSpace] = None
                expected_vm_capability, origin_vm_size, final_vm_size = resize.resize(
                    resize_action
                )
                break
            except Exception as identifier:
                if "no available size for resizing" in str(identifier):
                    raise SkippedException(str(identifier))
                print(str(identifier))
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
                    print(retry)
                    retry = retry + 1
                else:
                    raise identifier
                time.sleep(1)
            finally:
                if not hot_resize:
                    start_stop.start()
        assert expected_vm_capability, "fail to find proper vm size"

        test_result.information["final_vm_size"] = final_vm_size
        test_result.information["origin_vm_size"] = origin_vm_size
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

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        # resize cases will change vm size
        # therefore we mark the node dirty to prevent future testing on this environment
        node = kwargs["node"]
        node.mark_dirty()
