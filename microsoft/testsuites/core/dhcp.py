# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

from assertpy.assertpy import assert_that

from lisa import (
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    UnsupportedDistroException,
    simple_requirement,
)
from lisa.sut_orchestrator import AZURE, HYPERV, READY
from lisa.tools import Dhclient


@TestSuiteMetadata(
    area="core",
    category="functional",
    description="""
    This test suite covers DHCP functionalities.
    """,
    requirement=simple_requirement(unsupported_os=[]),
)
class Dhcp(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case check the timeout setting of DHCP on Azure equals or more
            than 300 seconds.

        """,
        priority=1,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY, HYPERV]),
    )
    def verify_dhcp_client_timeout(self, node: Node) -> None:
        dhclient = node.tools[Dhclient]
        try:
            timeout = dhclient.get_timeout()
        except UnsupportedDistroException as identifier:
            raise SkippedException(identifier)

        assert_that(timeout).described_as(
            "the DHCP client timeout should be set equal or more than 300 seconds"
            " to avoid provisioning timeout in Azure."
        ).is_greater_than_or_equal_to(300)
