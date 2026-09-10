# LISA Test Patterns

Canonical patterns for writing LISA test suites and cases. Copy these as starting
points.

## Basic Test Suite

```python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import Posix


@TestSuiteMetadata(
    area="<feature_area>",
    category="functional",
    description="""
    <Describe what this test suite validates.>
    """,
    requirement=simple_requirement(supported_os=[Posix]),
)
class MyFeature(TestSuite):
    @TestCaseMetadata(
        description="""
        <Describe what this test case verifies and the steps it takes.>
        """,
        priority=2,
        requirement=simple_requirement(
            supported_os=[Posix],
        ),
    )
    def verify_my_feature(self, node: Node, log: Logger) -> None:
        # Arrange
        tool = node.tools[SomeTool]

        # Act
        result = tool.some_method()

        # Assert
        assert_that(result).described_as(
            "Expected the tool to return a valid result"
        ).is_not_none()

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        log.info("Setting up test case")

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        log.info("Cleaning up test case")
```

## Test with Feature Requirement

```python
from lisa.features import Gpu, SerialConsole, StartStop

@TestCaseMetadata(
    description="""
    Verify GPU is detected and driver loads correctly.
    """,
    priority=1,
    requirement=simple_requirement(
        supported_os=[Posix],
        supported_features=[Gpu],
        min_gpu_count=1,
    ),
)
def verify_gpu_detection(self, node: Node, log: Logger) -> None:
    gpu = node.features[Gpu]
    # ... test logic
```

## Test with Multiple Nodes

```python
from lisa import Environment

@TestCaseMetadata(
    description="""
    Verify network connectivity between two nodes.
    """,
    priority=2,
    requirement=simple_requirement(
        min_count=2,
        supported_os=[Posix],
        min_nic_count=1,
    ),
)
def verify_inter_node_connectivity(
    self, environment: Environment, log: Logger
) -> None:
    node1 = environment.nodes[0]
    node2 = environment.nodes[1]
    # ... test logic
```

## Test with Cleanup (mark_dirty)

```python
@TestCaseMetadata(
    description="""
    Verify kernel parameter modification survives reboot.
    """,
    priority=2,
    requirement=simple_requirement(supported_os=[Posix]),
)
def verify_kernel_param(self, node: Node, log: Logger) -> None:
    try:
        grub = node.tools[GrubConfig]
        grub.set_kernel_cmdline_arg("my_param", "value")
        node.reboot()

        result = node.tools[Cat].read("/proc/cmdline", sudo=True)
        assert_that(result).described_as(
            "Kernel parameter should be present after reboot"
        ).contains("my_param=value")
    finally:
        node.mark_dirty()  # kernel params were modified
```

## Test with Skip

```python
from lisa import SkippedException

@TestCaseMetadata(
    description="""
    Verify feature X on supported kernels only.
    """,
    priority=2,
    requirement=simple_requirement(supported_os=[Posix]),
)
def verify_feature_x(self, node: Node, log: Logger) -> None:
    kernel_version = node.tools[Uname].get_linux_information().kernel_version_raw
    if kernel_version < "5.15":
        raise SkippedException(
            f"Feature X requires kernel >= 5.15, got {kernel_version}"
        )
    # ... test logic
```

## Assertion Patterns

```python
from assertpy import assert_that

# Value assertions
assert_that(result.exit_code).described_as(
    "Command should succeed"
).is_equal_to(0)

# String assertions
assert_that(result.stdout).described_as(
    "Output should contain expected module name"
).contains("my_module")

# Collection assertions
assert_that(devices).described_as(
    "At least one NVMe device should be present"
).is_not_empty()

assert_that(found_drivers).described_as(
    "All required drivers should be loaded"
).contains("hv_netvsc", "hv_storvsc")

# Length assertions (use native matcher)
assert_that(disks).described_as(
    "Expected exactly 2 data disks"
).is_length(2)

# Boolean assertions
assert_that(node.tools[KernelConfig].is_enabled("CONFIG_HYPERV")).described_as(
    "Hyper-V kernel config should be enabled"
).is_true()
```

## Logging Patterns

```python
# INFO — high-level progress (reads like a story)
log.info(f"Starting SRIOV validation on node '{node.name}'")
log.info(f"Found {len(devices)} NVMe devices, expected {expected_count}")
log.info(f"Reboot completed successfully in {elapsed:.2f}s")

# DEBUG — detailed diagnostics
log.debug(f"Command output: {result.stdout}")
log.debug(f"Parsed kernel version: {version}")
log.debug(f"NIC configuration: {nic_info}")
```
