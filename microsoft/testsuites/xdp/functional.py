# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import Any, List, cast

from assertpy import assert_that

from lisa import (
    Environment,
    LisaException,
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
from lisa.features import NetworkInterface, Sriov, Synthetic
from lisa.operating_system import BSD, Windows
from lisa.tools import Firewall, Ip, Kill, TcpDump
from lisa.tools.ping import INTERNET_PING_ADDRESS
from lisa.util import get_matched_str
from lisa.util.constants import SIGINT
from microsoft.testsuites.xdp.common import get_dropped_count, get_xdpdump
from microsoft.testsuites.xdp.xdpdump import BuildType
from microsoft.testsuites.xdp.xdptools import XdpTool


@TestSuiteMetadata(
    area="xdp",
    category="functional",
    description="""
    This test suite is to validate XDP functionality.
    """,
)
class XdpFunctional(TestSuite):
    # sample output:
    # 2458.952901 IP 20.83.220.172:unloading xdp program...
    # unloading xdp program...
    _UNLOAD_XDP_STR_PATTERN = re.compile("unloading xdp program...")

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        environment: Environment = kwargs.pop("environment")
        if isinstance(node.os, BSD) or isinstance(node.os, Windows):
            raise SkippedException(f"XDP is not supported in {node.os.name} yet.")

        for node in environment.nodes.list():
            node.tools[Firewall].stop()

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
            xdpdump = get_xdpdump(node)
            output = xdpdump.test_by_ping()

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
        xdpdump = get_xdpdump(xdp_node)

        remote_address = self._get_ping_address(environment)

        # test in SRIOV mode.
        output = xdpdump.test_by_ping(
            xdp_node.nics.default_nic, remote_address=remote_address
        )
        self._verify_xdpdump_result(output)

        try:
            # disable SRIOV
            network = xdp_node.features[NetworkInterface]
            assert_that(network.is_enabled_sriov()).described_as(
                "SRIOV must be enabled when start the test."
            ).is_true()
            network.switch_sriov(False)

            # test in synthetic mode
            output = xdpdump.test_by_ping(
                xdp_node.nics.default_nic, remote_address=remote_address
            )
            self._verify_xdpdump_result(output)
        finally:
            # enable SRIOV back to recover environment
            network.switch_sriov(True)

    @TestCaseMetadata(
        description="""
        It validates the XDP works with Synthetic network.

        The test step is the same as verify_xdp_basic, but it run once only.
        """,
        priority=2,
        requirement=simple_requirement(network_interface=Synthetic()),
    )
    def verify_xdp_synthetic(self, node: Node) -> None:
        xdpdump = get_xdpdump(node)
        output = xdpdump.test_by_ping()

        self._verify_xdpdump_result(output)

    @TestCaseMetadata(
        description="""
        It validates XDP with multiple nics.

        1. Check current image supports XDP or not.
        2. Install and validate xdpdump.
        """,
        priority=3,
        requirement=simple_requirement(min_nic_count=3),
    )
    def verify_xdp_multiple_nics(self, node: Node) -> None:
        xdpdump = get_xdpdump(node)
        for i in range(3):
            nic_info = node.nics.get_nic_by_index(i)
            output = xdpdump.test_by_ping(nic_name=nic_info.name)

            self._verify_xdpdump_result(output)

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
        # expect no response from the ping source side.
        captured_node = environment.nodes[0]
        default_nic = captured_node.nics.get_primary_nic()
        original_count = get_dropped_count(
            node=captured_node,
            nic=default_nic,
            previous_count=0,
            log=log,
        )
        self._test_with_build_type(
            environment=environment,
            captured_node=captured_node,
            case_name=case_name,
            build_type=BuildType.ACTION_DROP,
            expected_tcp_packet_count=5,
            failure_message="DROP mode must have and only have sent packets "
            "at the send side.",
            expected_ping_success=False,
        )
        drop_count = get_dropped_count(
            node=captured_node,
            nic=default_nic,
            previous_count=original_count,
            log=log,
        )
        assert_that(drop_count).described_as(
            "the source side should have 5 dropped packets."
        ).is_equal_to(5)

        # expect no packet from the ping target side
        captured_node = environment.nodes[1]
        default_nic = captured_node.nics.get_primary_nic()
        original_count = get_dropped_count(
            node=captured_node,
            nic=default_nic,
            previous_count=0,
            log=log,
        )
        self._test_with_build_type(
            environment=environment,
            captured_node=captured_node,
            case_name=case_name,
            build_type=BuildType.ACTION_DROP,
            expected_tcp_packet_count=0,
            failure_message="DROP mode must have no packet at target side.",
            expected_ping_success=False,
        )
        drop_count = get_dropped_count(
            node=captured_node,
            nic=default_nic,
            previous_count=original_count,
            log=log,
        )
        assert_that(drop_count).described_as(
            "the target side should have 5 dropped packets."
        ).is_equal_to(5)

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
    def verify_xdp_action_tx(self, environment: Environment, case_name: str) -> None:
        # tx has response packet from ping source side
        self._test_with_build_type(
            environment=environment,
            captured_node=environment.nodes[0],
            case_name=case_name,
            build_type=BuildType.ACTION_TX,
            expected_tcp_packet_count=10,
            failure_message="TX mode should receive response from ping source side.",
            expected_ping_success=True,
        )
        # tx has no packet from target side
        self._test_with_build_type(
            environment=environment,
            captured_node=environment.nodes[1],
            case_name=case_name,
            build_type=BuildType.ACTION_TX,
            expected_tcp_packet_count=0,
            failure_message="TX mode shouldn't capture any packets "
            "from the ping target node in tcp dump.",
            expected_ping_success=True,
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
        self, environment: Environment, case_name: str
    ) -> None:
        # expect no response from the ping source side.
        self._test_with_build_type(
            environment=environment,
            captured_node=environment.nodes[0],
            case_name=case_name,
            build_type=BuildType.ACTION_ABORTED,
            expected_tcp_packet_count=5,
            failure_message="DROP mode must have and only have sent packets "
            "at the send side.",
            expected_ping_success=False,
        )
        # expect no packet from the ping target side
        self._test_with_build_type(
            environment=environment,
            captured_node=environment.nodes[1],
            case_name=case_name,
            build_type=BuildType.ACTION_ABORTED,
            expected_tcp_packet_count=0,
            failure_message="ABORT mode must have no packet at target side.",
            expected_ping_success=False,
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
        xdpdump = get_xdpdump(xdp_node)
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
                xdpdump.test_by_ping(
                    xdp_node_nic_name,
                    remote_address=remote_address,
                    ping_package_size=mtu - 28,
                )
        finally:
            xdp_node_ip.set_mtu(xdp_node_nic_name, original_xdp_node_mtu)
            remote_ip.set_mtu(remote_nic_name, original_remote_mtu)

    @TestCaseMetadata(
        description="""
        It validates the XDP works with VF hot add/remove from API.

        1. Run xdp dump to drop and count packets.
        2. Remove VF from API.
        3. Run xdp dump to drop and count packets.
        5. Add VF back from API.
        6. Run xdp dump to drop and count packets.
        """,
        priority=3,
        requirement=simple_requirement(network_interface=Sriov()),
    )
    def verify_xdp_remove_add_vf(self, node: Node, log: Logger) -> None:
        xdpdump = get_xdpdump(node)

        nic_name = node.nics.default_nic
        nic_feature = node.features[NetworkInterface]
        default_nic = node.nics.get_primary_nic()

        try:
            # validate xdp works with VF
            original_count = get_dropped_count(
                node=node,
                nic=default_nic,
                previous_count=0,
                log=log,
            )
            output = xdpdump.test_by_ping(
                nic_name=nic_name,
                build_type=BuildType.ACTION_DROP,
                expected_ping_success=False,
                remote_address=INTERNET_PING_ADDRESS,
            )
            self._verify_xdpdump_result(output)
            drop_count = get_dropped_count(
                node=node,
                nic=default_nic,
                previous_count=original_count,
                log=log,
            )
            assert_that(drop_count).described_as(
                "the source side should have 5 dropped packets when VF is enabled."
            ).is_equal_to(5)

            # disable VF
            nic_feature.switch_sriov(False)

            default_nic = node.nics.get_primary_nic()
            # validate xdp works with synthetic
            original_count = get_dropped_count(
                node=node,
                nic=default_nic,
                previous_count=0,
                log=log,
            )
            output = xdpdump.test_by_ping(
                nic_name=nic_name,
                build_type=BuildType.ACTION_DROP,
                expected_ping_success=False,
                remote_address=INTERNET_PING_ADDRESS,
            )
            self._verify_xdpdump_result(output)
            drop_count = get_dropped_count(
                node=node,
                nic=default_nic,
                previous_count=original_count,
                log=log,
            )
            assert_that(drop_count).described_as(
                "There should be 5 dropped packets when VF is disabled."
            ).is_equal_to(5)

            # enable VF and validate xdp works with VF again
            nic_feature.switch_sriov(True)

            default_nic = node.nics.get_primary_nic()
            original_count = get_dropped_count(
                node=node,
                nic=default_nic,
                previous_count=0,
                log=log,
            )
            output = xdpdump.test_by_ping(
                nic_name=nic_name,
                build_type=BuildType.ACTION_DROP,
                expected_ping_success=False,
                remote_address=INTERNET_PING_ADDRESS,
            )
            self._verify_xdpdump_result(output)
            drop_count = get_dropped_count(
                node=node,
                nic=default_nic,
                previous_count=original_count,
                log=log,
            )
            assert_that(drop_count).described_as(
                "the source side should have 5 dropped packets when VF back again."
            ).is_equal_to(5)
        finally:
            # recover sriov to on, it prevents the test fails when the sriov is
            # off.
            nic_feature.switch_sriov(True)

    @TestCaseMetadata(
        description="""
        It runs all tests of xdp-tools. Check the official site for more
        details.

        https://github.com/xdp-project/xdp-tools
        """,
        priority=3,
    )
    def verify_xdp_community_test(self, node: Node) -> None:
        try:
            xdptool = node.tools[XdpTool]
        except UnsupportedDistroException as identifier:
            raise SkippedException(identifier)
        xdptool.run_full_test()

    def _test_with_build_type(
        self,
        environment: Environment,
        captured_node: Node,
        case_name: str,
        build_type: BuildType,
        expected_tcp_packet_count: int,
        failure_message: str,
        expected_ping_success: bool,
    ) -> None:
        ping_source_node = environment.nodes[0]

        xdpdump = get_xdpdump(captured_node)
        tcpdump = captured_node.tools[TcpDump]
        ping_address = self._get_ping_address(environment)

        pcap_filename = f"{case_name}.pcap"
        tcpdump.dump_async(
            ping_source_node.nics.default_nic,
            expression=f'"icmp and host {ping_address}"',
            packet_filename=pcap_filename,
        )
        xdpdump.test_by_ping(
            ping_source_node.nics.default_nic,
            remote_address=ping_address,
            build_type=build_type,
            expected_ping_success=expected_ping_success,
            ping_source_node=ping_source_node,
        )

        kill = captured_node.tools[Kill]
        kill.by_name("tcpdump", SIGINT)

        packets = tcpdump.parse(pcap_filename)
        ping_node = cast(RemoteNode, ping_source_node)
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

    def _verify_xdpdump_result(self, output: str) -> None:
        # xdpdump checks last line to see if it runs successfully.
        last_line = output.splitlines(keepends=False)[-1]

        if not get_matched_str(last_line, self._UNLOAD_XDP_STR_PATTERN):
            raise LisaException(
                "failed on matching xdpdump result, "
                "expected: unloading xdp program..."
            )
