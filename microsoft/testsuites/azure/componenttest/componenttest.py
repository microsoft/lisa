import asyncio
from typing import cast, Any
from assertpy import assert_that
from lisa.tools import Ping
from lisa.operating_system import CBLMariner
from lisa.util import UnsupportedDistroException, SkippedException, LisaException
from lisa import (
    Environment,
    Logger,
    RemoteNode,
    TestSuite,
    TestSuiteMetadata,
    TestCaseMetadata,
)

@TestSuiteMetadata(
    area="component_test",
    category="ComponentTest",
    description="""
    This test suite verifies that the required network security components are functioning correctly.
    """
)

class ComponentTest(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: RemoteNode = kwargs["node"] 
        if not isinstance(node.os, CBLMariner) or node.os.information.version < "3.0.0":
            raise SkippedException(
                UnsupportedDistroException(
                    node.os, "Component testsuite is intended to run only on AzureLinux 3.0 or greater than that."
                )
            )

    NATTABLE = "nat"
    NATCHAIN = [
        "allowlayer4",
    ]
    FILTERTABLE = "filter"
    FILTERCHAIN = [
        "LOG",
        "MARK_ALLOWED_AND_ACCEPT",
        "LOG_DROP_OTHER"
    ]
    PACKETCOUNT = 40
    VMCOUNT = 1
    NICCOUNT = 1
    CONNMARKACTIVE = "0x100"
    CONNMARKSRC = "10.0.0.0"
    CONNMARKDEST = "10.0.0.1"
    CONNMARKPROTO = "2"
    CONNMARKTIMEOUT = "120"
    IPSETNAME = "testset"
    IPSETTESTADDRULE = [
        f"-A OUTPUT -p icmp -m set --match-set {IPSETNAME} dst -j DROP",
        "-A OUTPUT -j ACCEPT"
    ]
    IPSETTESTDELETERULES = [
        "OUTPUT -j ACCEPT"
    ]
    PREROUTINGCHAIN = [
        '-A PREROUTING -i eth0 -p tcp -m comment --comment "collection: tcp name: tcptraffic" -j allowlayer4',
        '-A PREROUTING -i eth0 -p udp -m comment --comment "collection: udp name: udptraffic" -j allowlayer4',
        '-A PREROUTING -i eth0 -p icmp -m comment --comment "collection: icmp name: icmptraffic" -j allowlayer4'
    ]
    FORWARDCHAIN = [
        '-A FORWARD -i eth0 -p tcp -m conntrack --ctstate NEW -m comment --comment "collection: tcp name: tcptraffic" -j LOG --log-prefix "allowlayer4: " --log-level 6',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate NEW -m comment --comment "collection: udp name: udptraffic" -j LOG --log-prefix "allowlayer4: " --log-level 6',
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate NEW -m comment --comment "collection: icmp name: icmptraffic" -j LOG --log-prefix "allowlayer4: " --log-level 6',
        '-A FORWARD -i eth0 -p tcp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "collection: tcp name: tcptraffic" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "collection: udp name: udptraffic" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "collection: icmp name: icmptraffic" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p tcp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "collection: tcp name: tcptraffic" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "collection: udp name: udptraffic" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "collection: icmp name: icmptraffic" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -j LOG_DROP_OTHER'
    ]

    @TestCaseMetadata(
        description="""
        This test suite validates the creation and management of 
        iptables chains, ipset operations, and conntrack entries to ensure that 
        network policy rules are enforced as expected.
        """,
        priority=2
    )

    def verify_network_component(self, environment: Environment, log: Logger) -> None:

        test_node = cast(RemoteNode, environment.nodes[0])

        required_components = ["conntrack", "ipset"]
        for component in required_components:
            test_node.os.install_packages(component)
        
        #conntrack test
        log.info(f"Running conntrack test in node : {test_node.name}")
        test_conntrack(self, test_node,log)

        #ipset test
        log.info(f"Running ipset test in node : {test_node.name}")
        test_ipset(self, test_node, log)

        #IPTableTest
        log.info(f"Running IPTables test in node : {test_node.name}")
        test_iptables(self, test_node, log)

def test_ipset(self, node: RemoteNode, log: Logger):

    log.info("Adding new ip set")
    cmd = f"ipset create {self.IPSETNAME} hash:ip"
    log.info(f"Creating set named {cmd} in ipset")
    result = node.execute(cmd, sudo=True)
    cmd = f"ipset add {self.IPSETNAME} 8.8.8.8"
    log.info(f"Adding ip 8.8.8.8 in ipset {self.IPSETNAME} {cmd}")
    result = node.execute(cmd, sudo=True)
    log.info(f"Remove {self.IPSETTESTDELETERULES} and Add {self.IPSETTESTADDRULE} to block the outgoing traffic to 8.8.8.8")
    __add_iptable_rules(node, self.FILTERTABLE, self.IPSETTESTADDRULE, log)
    __remove_iptable_rules(node, self.IPSETTESTDELETERULES, log)
    log.info(f"Added IPTable Rule in OUTPUT Chain to block outgoing traffic to 8.8.8.8")
    log.info(f"Send ICMP traffic to destination 8.8.8.8 to verify whether traffic is blocked using ipset")    
    result = node.tools[Ping].ping_async(target="8.8.8.8", count=self.PACKETCOUNT, sudo=True)
    ping_result = result.wait_result()
    log.debug(f"ICMP traffic result for destination 8.8.8.8 : {ping_result} ")
    if "100% packet loss" not in ping_result.stdout:
        raise LisaException("ICMP traffic is being allowed eventhough the IPTables rules has been added to drop it")

def test_conntrack(self, node: RemoteNode, log: Logger):

    log.info("Adding entry in conntrack ")
    cmd = f"conntrack -I -s {self.CONNMARKSRC} -d {self.CONNMARKDEST} --protonum {self.CONNMARKPROTO} --timeout {self.CONNMARKTIMEOUT} --mark={self.CONNMARKACTIVE}"
    log.info(f"Adding this entry {cmd} to conntrack")
    result = node.execute(cmd, sudo=True)
    log.debug(f'Result for adding conntrack entry : {result.stdout}')
    if "1 flow entries have been created" not in result.stdout:
        raise LisaException(f"Failed in adding entry to conntrack, Result: {result}")
    log.info("Successfully added entry to conntrack, now update the entry")
    cmd = f"conntrack -U --mark 0/{self.CONNMARKACTIVE}"
    log.info(f"Update the conntrack entry with command : {cmd}")
    result = node.execute(cmd, sudo=True)
    if "flow entries have been updated" not in result.stdout:
        raise LisaException(f"Failed in updating conntrack entry, Result: {result}")
    __verify_conntrack_entry(node, self.CONNMARKSRC, self.CONNMARKDEST, self.CONNMARKPROTO, "0", log)

def test_iptables(self, node: RemoteNode, log: Logger):
    
    log.info("Add Rules To PreRouting Chain and verify the iptables")
    __create_iptable_chain(node, self.NATTABLE, self.NATCHAIN, log)
    __add_iptable_rules(node, self.NATTABLE, self.PREROUTINGCHAIN, log)
    if not asyncio.run(__verify_iptables(__iptable_dump(node, log), self.PREROUTINGCHAIN, log)):
       raise LisaException("IPTables test failed in PreRouting Chain")
    log.info("Add Rules To Forward Chain and verify the iptables")
    __create_iptable_chain(node, self.FILTERTABLE, self.FILTERCHAIN, log)
    __add_iptable_rules(node, self.FILTERTABLE, self.FORWARDCHAIN, log)
    if not asyncio.run(__verify_iptables(__iptable_dump(node, log), self.FORWARDCHAIN, log)):
        raise LisaException("IPTables test failed in Forwarding Chain")

def __add_iptable_rules(node: RemoteNode, ipTable: str, iptable_rules: list[str], log: Logger):
    for iptable_rule in iptable_rules:
        cmd = f"iptables -t {ipTable} {iptable_rule}"
        log.debug(f"Adding IP Table Rule {iptable_rule} to IPTables : {cmd}")
        node.execute(cmd, sudo=True)

def __create_iptable_chain(node: RemoteNode, ipTable: str, iptable_chains: list[str], log: Logger):
    for iptable_chain in iptable_chains:
        cmd = f"iptables -t {ipTable} -N {iptable_chain}"
        log.debug(f"Creating new chain {iptable_chain} in IPTables : {cmd}")
        node.execute(cmd, sudo=True)

async def __verify_iptables(iptables_dump: str, array_to_match: list[str], log: Logger):
    iptables = iptables_dump.splitlines()
    for iptable_entry in array_to_match:
        if iptable_entry not in iptables:
            log.debug(f"Not matched  : {iptable_entry}")
            return False
    return True

def __iptable_dump(node: RemoteNode, log: Logger):
    iptable_dump_result = node.execute("iptables-save", sudo=True)
    log.debug(f"IPTable Dump Result : {iptable_dump_result.stdout}")
    return iptable_dump_result.stdout

def __verify_conntrack_entry(node: RemoteNode, client_nic_ipaddr: str, server_nic_ipaddr: str, protocol: str, mask: str, log: Logger):
    log.info(f"Verifying conntrack entry for Protocol {protocol} from {client_nic_ipaddr} to {server_nic_ipaddr} in node {node.name}")
    result = node.execute(f"bash -c \"conntrack -L | grep '{client_nic_ipaddr}' | grep '{server_nic_ipaddr}' | grep '{protocol}' | grep '{mask}'\"", sudo=True)
    if len(result.stdout.splitlines()) > 1:
        log.info("Conntrack Entry Found")
    else:
        raise Exception(f"Conntrack entry not found for Protocol {protocol} from {client_nic_ipaddr} to {server_nic_ipaddr}")

def __remove_iptable_rules(node: RemoteNode, iptable_rules: list[str], log: Logger):
    for iptable_rule in iptable_rules:
        log.info(f"Removing rule {iptable_rule} from iptables")
        node.execute(f"iptables -D {iptable_rule}", sudo=True)