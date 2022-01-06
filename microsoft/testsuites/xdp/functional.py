# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List, cast

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    RemoteNode,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    UnsupportedDistroException,
    simple_requirement,
)
from lisa.features import NetworkInterface, Sriov
from lisa.tools import Ip, TcpDump
from microsoft.testsuites.xdp.xdpdump import ActionType, XdpDump


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
        requirement=simple_requirement(min_count=2, network_interface=Sriov()),
    )
    def verify_xdp_sriov_failsafe(self, environment: Environment) -> None:
        xdp_node = environment.nodes[0]
        xdpdump = self._get_xdpdump(xdp_node)

        remote_address = self._get_ping_address(environment)

        # test in SRIOV mode.
        output = xdpdump.test(xdp_node.nics.default_nic, remote_address=remote_address)
        self._verify_xdpdump_result(output)

        try:
            # disable SRIOV
            network = xdp_node.features[NetworkInterface]
            assert_that(network.is_enabled_sriov()).described_as(
                "SRIOV must be enabled when start the test."
            ).is_true()
            network.switch_sriov(False)

            # test in synthetic mode
            output = xdpdump.test(
                xdp_node.nics.default_nic, remote_address=remote_address
            )
            self._verify_xdpdump_result(output)
        finally:
            # enable SRIOV back to recover environment
            network.switch_sriov(True)

    @TestCaseMetadata(
        description="""
        It validates the XDP with action DROP.

        1. start tcpdump with icmp filter.
        2. start xdpdump.
        3. run ping 5 times.
        4. check tcpdump with 5 packets.
        """,
        priority=2,
        requirement=simple_requirement(min_count=2),
    )
    def verify_xdp_action_drop(
        self, environment: Environment, case_name: str, log: Logger
    ) -> None:
        self._test_with_action(
            environment,
            case_name,
            ActionType.DROP,
            5,
            "DROP mode must have and only have sent packets.",
            False,
        )

    @TestCaseMetadata(
        description="""
        It validates the XDP with action TX.

        1. start tcpdump with icmp filter.
        2. start xdpdump.
        3. run ping 5 times.
        4. check tcpdump with 5 packets, because the icmp is replied in xdp
           level.
        """,
        priority=2,
        requirement=simple_requirement(min_count=2),
    )
    def verify_xdp_action_tx(
        self, environment: Environment, case_name: str, log: Logger
    ) -> None:
        try:
            self._test_with_action(
                environment,
                case_name,
                ActionType.TX,
                5,
                "TX mode must get only sent packets",
                True,
            )
        except AssertionError as identifer:
            raise SkippedException(
                "It needs more investigation on why tcpdump capture all packets. "
                "The expected captured packets should be 5, but it's 10."
                f"{identifer}"
            )

    @TestCaseMetadata(
        description="""
        It validates the XDP with action ABORT.

        1. start tcpdump with icmp filter.
        2. start xdpdump.
        3. run ping 5 times.
        4. check tcpdump with 5 packets.
        """,
        priority=3,
        requirement=simple_requirement(min_count=2),
    )
    def verify_xdp_action_aborted(
        self, environment: Environment, case_name: str, log: Logger
    ) -> None:
        self._test_with_action(
            environment,
            case_name,
            ActionType.ABORTED,
            5,
            "ABORT mode must have and only have sent packets.",
            False,
        )

    @TestCaseMetadata(
        description="""
        It validates XDP with different MTU

        1. Check current image supports XDP or not.
        2. change MTU to 1500, 2000, 3506 to test XDP.
        """,
        priority=3,
        requirement=simple_requirement(min_count=2),
    )
    def verify_xdp_with_different_mtu(self, environment: Environment) -> None:
        xdp_node = environment.nodes[0]
        remote_node = environment.nodes[1]
        xdpdump = self._get_xdpdump(xdp_node)
        remote_address = self._get_ping_address(environment)
        tested_mtu: List[int] = [1500, 2000, 3506]

        xdp_node_nic_name = xdp_node.nics.default_nic
        remote_nic_name = remote_node.nics.default_nic

        xdp_node_ip = xdp_node.tools[Ip]
        remote_ip = remote_node.tools[Ip]

        original_xdp_node_mtu = xdp_node_ip.get_mtu(xdp_node_nic_name)
        original_remote_mtu = remote_ip.get_mtu(remote_nic_name)

        try:
            for mtu in tested_mtu:
                xdp_node_ip.set_mtu(xdp_node_nic_name, mtu)
                remote_ip.set_mtu(remote_nic_name, mtu)

                # tested mtu equals (ping mtu - IP headr (20) - ICMP header (8))
                xdpdump.test(
                    xdp_node_nic_name,
                    remote_address=remote_address,
                    ping_package_size=mtu - 28,
                )
        finally:
            xdp_node_ip.set_mtu(xdp_node_nic_name, original_xdp_node_mtu)
            remote_ip.set_mtu(remote_nic_name, original_remote_mtu)

    def _test_with_action(
        self,
        environment: Environment,
        case_name: str,
        action: ActionType,
        expected_tcp_packet_count: int,
        failure_message: str,
        expected_ping_success: bool,
    ) -> None:
        node = environment.nodes[0]
        xdpdump = self._get_xdpdump(node)
        tcpdump = node.tools[TcpDump]
        remote_address = self._get_ping_address(environment)

        pcap_filename = f"{case_name}.pcap"
        dump_process = tcpdump.dump_async(
            node.nics.default_nic, filter="icmp", packet_filename=pcap_filename
        )
        xdpdump.test(
            node.nics.default_nic,
            remote_address=remote_address,
            action_type=action,
            expected_ping_success=expected_ping_success,
        )

        # the tcpdump exits with 124 as normal.
        dump_process.wait_result(
            expected_exit_code=124,
            expected_exit_code_failure_message="error on wait tcpdump",
        )

        packets = tcpdump.parse(pcap_filename)
        ping_node = cast(RemoteNode, environment.nodes[1])
        packets = [
            x
            for x in packets
            if x.destination == ping_node.internal_address
            or x.source == ping_node.internal_address
        ]
        assert_that(packets).described_as(failure_message).is_length(
            expected_tcp_packet_count
        )

    def _get_ping_address(self, environment: Environment) -> str:
        ping_node = environment.nodes[1]
        assert isinstance(
            ping_node, RemoteNode
        ), "The pinged node must be remote node with connection information"

        return ping_node.internal_address

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
