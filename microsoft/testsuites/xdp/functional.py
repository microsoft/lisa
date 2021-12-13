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
    simple_requirement,
)
from lisa.features import NetworkInterface, Sriov
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
        It validates the basic functionality of XDP. It runs multiple times to
        test the load/unload. It includes below steps,

        1. Check current image supports XDP or not.
        2. Install and validate xdpdump.
        """,
        priority=1,
    )
    def verify_xdp_basic(self, node: Node) -> None:
        for _ in range(3):
            xdpdump = self._get_xdpdump(node)
            output = xdpdump.test()

            self._verify_xdpdump_result(output)

    @TestCaseMetadata(
        description="""
        It validates the XDP works with Synthetic network when SRIOV is
        disabled.

        1. Test in SRIOV mode.
        2. Disable the SRIOV.
        3. Test in Synthetic mode.
        """,
        priority=2,
        requirement=simple_requirement(network_interface=Sriov()),
    )
    def verify_xdp_sriov_failsafe(self, node: Node) -> None:
        xdpdump = self._get_xdpdump(node)

        # test in SRIOV mode.
        output = xdpdump.test()
        self._verify_xdpdump_result(output)

        try:
            # disable SRIOV
            network = node.features[NetworkInterface]
            assert_that(network.is_enabled_sriov()).described_as(
                "SRIOV must be enabled when start the test."
            ).is_true()
            network.switch_sriov(False)

            # test in synthetic mode
            output = xdpdump.test()
            self._verify_xdpdump_result(output)
        finally:
            # enable SRIOV back to recover environment
            network.switch_sriov(True)

    def _get_xdpdump(self, node: Node) -> XdpDump:
        try:
            xdpdump = node.tools[XdpDump]
        except UnsupportedDistroException as identifier:
            raise SkippedException(identifier)

        return xdpdump

    def _verify_xdpdump_result(self, output: str) -> None:
        # xdpdump checks last line to see if it runs successfully.
        last_line = output.splitlines(keepends=False)[-1]

        assert_that(last_line).described_as(
            "failed on matching xdpdump result."
        ).is_equal_to("unloading xdp program...")
