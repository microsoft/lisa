# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.environment import EnvironmentStatus
from lisa.tools import Dmesg, Lsvmbus


@TestSuiteMetadata(
    area="ACC_CVM",
    category="functional",
    description="""
    This test suite ensures configuration and devices for CVM
    """,
)
class CVMSuite(TestSuite):
    @TestCaseMetadata(
        description="""
        This case verifies that lsvmbus only shows devices
        that are allowed in a CVM guest

        Steps:
        1. Call lsvmbus
        2. Iterate through list returned by lsvmbus to ensure all devices
           listed are included in valid_class_ids
        """,
        priority=1,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
        ),
    )
    def verify_lsvmbus(self, log: Logger, node: Node) -> None:
        valid_class_ids = {
            "ba6163d9-04a1-4d29-b605-72e2ffb1dc7f": "Synthetic SCSI Controller",
            "f8615163-df3e-46c5-913f-f2d2f965ed0e": "Synthetic network adapter",
            "9527e630-d0ae-497b-adce-e80ab0175caf": "[Time Synchronization]",
            "57164f39-9115-4e78-ab55-382f3bd5422d": "[Heartbeat]",
            "0e0b6031-5213-4934-818b-38d90ced39db": "[Operating system shutdown]",
        }
        lsvmbus_tool = node.tools[Lsvmbus]
        device_list = lsvmbus_tool.get_device_channels()
        class_id_list = [device.class_id for device in device_list]
        assert_that(class_id_list).is_subset_of(list(valid_class_ids.keys()))

    @TestCaseMetadata(
        description="""
        This case verifies the isolation config on guest

        Steps:
        1. Call dmesg
        2. Check to ensure config a is 0x1
        3. Check to ensure config b is 0xba2
        """,
        priority=1,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
        ),
    )
    def verify_isolation_config(self, log: Logger, node: Node) -> None:
        dmesg_tool = node.tools[Dmesg]
        isolation_config = dmesg_tool.get_isolation_config()
        config_a = hex(int(isolation_config["config_a"], 16))
        config_b = hex(int(isolation_config["config_b"], 16))
        assert_that(config_b).is_equal_to(hex(0xBA2))
        assert_that(config_a).is_equal_to(hex(0x1))
