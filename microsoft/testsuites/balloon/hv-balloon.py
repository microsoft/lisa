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
from lisa.base_tools import Cat
from lisa.sut_orchestrator import AZURE, READY
from lisa.tools import Dmesg, Lsmod, Uname
from lisa.util import SkippedException


@TestSuiteMetadata(
    area="hv-balloon",
    category="functional",
    description="""
    This test suite uses to verify hv-balloon driver sanity.
    """,
    requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
)
class Balloon(TestSuite):
    @TestCaseMetadata(
        description="""
        This case is to check whether the hyperv_balloon driver had loaded successfully.
        Once driver is loaded it should appear in `lsmod` output.

        Steps,
        1. lsmod
        2. Check if hyperv_ballon exist in the list.
        """,
        priority=2,
        use_new_environment=True,
    )
    def verify_balloon_driver(self, node: Node, log: Logger) -> None:
        lsmod = node.tools[Lsmod]
        assert_that(lsmod.module_exists("hv_balloon")).described_as(
            "hyperv_balloon module is absent"
        ).is_equal_to(True)

    @TestCaseMetadata(
        description="""
        This testcase is to check if the hv_balloon driver has registered correctly.
        It also checks if the hv_balloon driver is registered with the right protocol version.

        Step,
        1. Check dmesg if it contains hv-balloon driver registration string
        2. Check dmesg if it contains hv-balloon protocol version number string
        """,
        priority=2,
    )
    def verify_dmesg_for_registration(self, node: Node, log: Logger) -> None:
        balloon_reg_str = "registering driver hv_balloon"
        balloon_drv_proto_str = "hv_balloon: Using Dynamic Memory protocol version 2.0"

        dmesg = node.tools[Dmesg]

        assert_that(dmesg.get_output()).contains(balloon_reg_str)
        assert_that(dmesg.get_output()).contains(balloon_drv_proto_str)

