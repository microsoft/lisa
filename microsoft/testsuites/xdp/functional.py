# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from assertpy import assert_that

from lisa import (
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    UnsupportedDistroException,
)
from microsoft.testsuites.xdp.xdpdump import XdpDump


@TestSuiteMetadata(
    area="xdp",
    category="functional",
    description="""
    This test suite is to validate XDP fuctionality.
    """,
)
class XdpFunctional(TestSuite):  # noqa
    @TestCaseMetadata(
        description="""
        It validates the basic functionality of XDP. It includes,

        1. Check current image supports XDP or not.
        2. Install and validate xdpdump.
        """,
        priority=1,
    )
    def verify_xdp_basic(self, node: Node) -> None:
        try:
            xdpdump = node.tools[XdpDump]
        except UnsupportedDistroException as identifier:
            raise SkippedException(identifier)
        output = xdpdump.test()

        # xdpdump checks last line to see if it runs successfully.
        last_line = output.splitlines(keepends=False)[-1]

        assert_that(last_line).described_as(
            "failed on matching xdpdump result."
        ).is_equal_to("unloading xdp program...")
