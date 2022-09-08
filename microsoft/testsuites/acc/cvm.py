# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re

from assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.tools import Dmesg, Lsvmbus
from lisa.util import LisaException


@TestSuiteMetadata(
    area="ACC_CVM",
    category="functional",
    description="""
    This test suite ensures correct configuration and allowed devices for CVM
    """,
)
class CVMSuite(TestSuite):
    # [    0.000000] Hyper-V: Isolation Config: Group A 0x1, Group B 0xba2
    __isolation_config_pattern = re.compile(
        r"\[\s+\d+.\d+\]\s+Hyper-V: Isolation Config: Group A."
        r"(?P<config_a>(0x[a-z,A-Z,0-9]+)), Group B.(?P<config_b>(0x[a-z,A-Z,0-9]+))"
    )

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
        1. Call dmesg to get output
        2. Find isolation config in output
        3. Check to ensure config a is 0x1
        4. Check to ensure config b is 0xba2
        """,
        priority=1,
    )
    def verify_isolation_config(self, log: Logger, node: Node) -> None:
        dmesg_tool = node.tools[Dmesg]
        dmesg_output = dmesg_tool.get_output()
        isolation_config = re.search(self.__isolation_config_pattern, dmesg_output)
        if isolation_config is not None:
            config_a = isolation_config.group("config_a")
            config_b = isolation_config.group("config_b")
            log.debug(f"Isolation Config is Group A:{config_a}, Group B:{config_b}")
        else:
            raise LisaException("No find matched Isolation Config in dmesg")
        config_a = hex(int(config_a, 16))
        config_b = hex(int(config_b, 16))
        assert_that(config_b).is_equal_to(hex(0xBA2))
        assert_that(config_a).is_equal_to(hex(0x1))
