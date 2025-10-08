# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from typing import Any, cast

from lisa import (
    Environment,
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.operating_system import CBLMariner
from lisa.tools import Conntrack, Ipset, Iptables, Ping
from lisa.util import LisaException, SkippedException, UnsupportedDistroException


@TestSuiteMetadata(
    area="component_test",
    category="functional",
    description="""
    This test suite validates the core functionality of network security components
    such as conntrack, ipset, and iptables. It ensures that connection tracking,
    IP-based filtering, and custom rule management operate as expected
    """,
)
class NetworkComponentTest(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: RemoteNode = kwargs["node"]
        if not isinstance(node.os, CBLMariner) or node.os.information.version < "3.0.0":
            raise SkippedException(
                UnsupportedDistroException(
                    node.os, "Intended to run on CBLMariner 3.0 or higher"
                )
            )

    NATTABLE = "nat"
    NATCHAIN = [
        "allowlayer4",
    ]
    FILTERTABLE = "filter"
    FILTERCHAIN = ["LOG", "MARK_ALLOWED_AND_ACCEPT", "LOG_DROP_OTHER"]
    PACKETCOUNT = 40
    VMCOUNT = 1
    NICCOUNT = 1
    CONNMARKACTIVE = "0x100"
    CONNMARKSRC = "10.0.0.0"
    CONNMARKDEST = "10.0.0.1"
    CONNMARKPROTO = 2
    CONNMARKTIMEOUT = 120
    IPSETIP = "8.8.8.8"
    IPSETNAME = "testset"
    IPSETTESTADDRULE = [
        f"-A OUTPUT -p icmp -m set --match-set {IPSETNAME} dst -j DROP",
        "-A OUTPUT -j ACCEPT",
    ]
    IPSETTESTDELETERULES = ["OUTPUT -j ACCEPT"]
    PREROUTINGCHAIN = [
        '-A PREROUTING -i eth0 -p tcp -m comment --comment "collection: tcp name: tcptraffic" -j allowlayer4', # noqa E501
        '-A PREROUTING -i eth0 -p udp -m comment --comment "collection: udp name: udptraffic" -j allowlayer4', # noqa E501
        '-A PREROUTING -i eth0 -p icmp -m comment --comment "collection: icmp name: icmptraffic" -j allowlayer4', # noqa E501
    ]
    FORWARDCHAIN = [
        '-A FORWARD -i eth0 -p tcp -m conntrack --ctstate NEW -m comment --comment "collection: tcp name: tcptraffic" -j LOG --log-prefix "allowlayer4: " --log-level 6', # noqa E501
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate NEW -m comment --comment "collection: udp name: udptraffic" -j LOG --log-prefix "allowlayer4: " --log-level 6', # noqa E501
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate NEW -m comment --comment "collection: icmp name: icmptraffic" -j LOG --log-prefix "allowlayer4: " --log-level 6', # noqa E501
        '-A FORWARD -i eth0 -p tcp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "collection: tcp name: tcptraffic" -j MARK_ALLOWED_AND_ACCEPT', # noqa E501
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "collection: udp name: udptraffic" -j MARK_ALLOWED_AND_ACCEPT', # noqa E501
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "collection: icmp name: icmptraffic" -j MARK_ALLOWED_AND_ACCEPT', # noqa E501
        '-A FORWARD -i eth0 -p tcp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "collection: tcp name: tcptraffic" -j MARK_ALLOWED_AND_ACCEPT', # noqa E501
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "collection: udp name: udptraffic" -j MARK_ALLOWED_AND_ACCEPT', # noqa E501
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "collection: icmp name: icmptraffic" -j MARK_ALLOWED_AND_ACCEPT', # noqa E501
        "-A FORWARD -i eth0 -j LOG_DROP_OTHER",
    ]

    @TestCaseMetadata(
        description="""
        This test case will validate that conntrack can successfully create a connection
        entry for an unknown protocol with a specified connection mark, and verify that
        the mark can be reset correctly for such unknown protocol entries.
        """,
        priority=2,
    )
    def verify_net_conntrack(self, environment: Environment, log: Logger) -> None:
        test_node = cast(RemoteNode, environment.nodes[0])
        conntrack = test_node.tools[Conntrack]

        # Insert a entry to conntrack table with unknown protocol entry with mark
        log.info(
            f"Create a conntrack entry for unknown protocol {self.CONNMARKPROTO} "
            f"with mark {self.CONNMARKACTIVE}"
        )
        conntrack.create_entry(
            src_ip=self.CONNMARKSRC,
            dst_ip=self.CONNMARKDEST,
            protonum=self.CONNMARKPROTO,
            timeout=self.CONNMARKTIMEOUT,
            mark=self.CONNMARKACTIVE,
        )

        # Reset the mark for all the entries to 0
        log.info("Reset the mark for all the conntrack entries to 0")
        conntrack.update_entry(mark=f"0/{self.CONNMARKACTIVE}")

        log.info(
            "Successfully verified the conntrack entry for "
            "unknown protocol with mark reset to 0"
        )

    @TestCaseMetadata(
        description="""
        This test will verify ipset functionality by ensuring IP-based blocking
        via iptables is correctly enforced.
        """,
        priority=2,
    )
    def verify_net_ipset(self, environment: Environment, log: Logger) -> None:
        test_node = cast(RemoteNode, environment.nodes[0])
        ipset = test_node.tools[Ipset]
        iptables = test_node.tools[Iptables]

        # Create a new ipset of type hash ip
        log.info(f"Creating new ipset named {self.IPSETNAME}")
        ipset.create_ipset(set_name=self.IPSETNAME, set_type="ip")

        # Add a new ip to the created ipset
        log.info(f"Adding new ip {self.IPSETIP} to ipset {self.IPSETNAME}")
        ipset.add_ip(set_name=self.IPSETNAME, ip_address=self.IPSETIP)

        # Add and remove specific iptables rule to block the outgoing traffic
        log.info(
            f"Remove {self.IPSETTESTDELETERULES} and Add {self.IPSETTESTADDRULE} "
            "to block the outgoing traffic to 8.8.8.8"
        )
        iptables.add_iptable_rules(
            table_name=self.FILTERTABLE, rules=self.IPSETTESTADDRULE
        )
        iptables.remove_iptable_rules(
            rules=self.IPSETTESTDELETERULES
        )

        # Send traffic to verify whether traffic is being blocked using ipset or not
        log.info(
            f"Send ICMP traffic to destination {self.IPSETIP} "
            "to verify whether traffic is blocked using ipset"
        )
        ping = test_node.tools[Ping]
        result = ping.ping_async(target=self.IPSETIP, count=self.PACKETCOUNT, sudo=True)
        ping_result = result.wait_result()
        log.debug(
            f"ICMP traffic result for destination {self.IPSETIP}:{ping_result} "
        )
        if "100% packet loss" not in ping_result.stdout:
            raise LisaException(
                "ICMP traffic is being allowed eventhough the IPTables rules "
                "has been added to drop it"
            )

    @TestCaseMetadata(
        description="""
        This test will verify iptables functionality by ensuring that custom chains
        and rules can be created with log prefixes
        """,
        priority=2,
    )
    def verify_net_iptables(self, environment: Environment, log: Logger) -> None:
        test_node = cast(RemoteNode, environment.nodes[0])

        iptables = test_node.tools[Iptables]

        # Create a new chain in nat table
        log.info(f"Create new chain {self.NATCHAIN} in {self.NATTABLE} table")
        iptables.create_iptable_chain(
            table_name=self.NATTABLE,
            chain_names=self.NATCHAIN,
        )

        # Add rules to prerouting chain in nat table
        log.info(
            f"Add rule {self.PREROUTINGCHAIN} PREROUTING chain in {self.NATTABLE} table"
        )
        iptables.add_iptable_rules(table_name=self.NATTABLE, rules=self.PREROUTINGCHAIN)

        # Add rules to forward chain in filter table
        log.info(
            f"Add rules {self.FORWARDCHAIN} to "
            f"FORWARD chain in {self.FILTERTABLE} table"
        )
        iptables.add_iptable_rules(table_name=self.FILTERTABLE, rules=self.FORWARDCHAIN)
