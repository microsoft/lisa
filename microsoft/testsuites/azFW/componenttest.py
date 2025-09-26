import asyncio
from typing import cast
from assertpy import assert_that
from lisa.tools import Ping
from lisa import (
    Environment,
    Logger,
    RemoteNode,
    TestSuite,
    TestSuiteMetadata,
    TestCaseMetadata,
    simple_requirement
)

@TestSuiteMetadata(
    area="azure-firewall",
    category="FirewallComponentTest",
    description="""
    This test suite will verify all the components that is being used by Azure Firewall Features
    """,
    requirement=simple_requirement(min_count=1, min_nic_count=1),
)

class AzureFirewallComponentTest(TestSuite):

    NATTABLE = "nat"
    NATCHAIN = [
        "L4_ALLOWED"
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
        '-A PREROUTING -i eth0 -p tcp -m comment --comment "RC: netRuleCollection Rule: netRule" -j L4_ALLOWED',
        '-A PREROUTING -i eth0 -p udp -m comment --comment "RC: netRuleCollection Rule: netRule" -j L4_ALLOWED',
        '-A PREROUTING -i eth0 -p icmp -m comment --comment "RC: netRuleCollection Rule: netRule" -j L4_ALLOWED'
    ]
    FORWARDCHAIN = [
        '-A FORWARD -i eth0 -p tcp -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: netRule" -j LOG --log-prefix "AZFW_NR_ACCEPT_1: " --log-level 6',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: netRule" -j LOG --log-prefix "AZFW_NR_ACCEPT_1: " --log-level 6',
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: netRule" -j LOG --log-prefix "AZFW_NR_ACCEPT_1: " --log-level 6',
        '-A FORWARD -i eth0 -p tcp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "RC: netRuleCollection Rule: netRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "RC: netRuleCollection Rule: netRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "RC: netRuleCollection Rule: netRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p tcp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "RC: netRuleCollection Rule: netRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "RC: netRuleCollection Rule: netRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "RC: netRuleCollection Rule: netRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -j LOG_DROP_OTHER'
    ]

    @TestCaseMetadata(
        description="""
        This test case will verify all the components that is being used in Azure Firewall to server Network Rule Feature
        """,
        priority=1
    )

    def network_component_test(self, environment: Environment, log: Logger) -> None:

        testNode = cast(RemoteNode, environment.nodes[0])

        #conntrack test
        log.info(f"Running conntrack test in node : {testNode.name}")
        assert_that(
            testconntrack(self, testNode,log)
        ). described_as(
            f"Azure Firewall Component Test failed in connmark"
        ).is_equal_to(True)

        #ipset test
        log.info(f"Running ipset test in node : {testNode.name}")
        assert_that(
            testIPSet(self, testNode, log)
        ).described_as(
            f"Azure Firewall Component test failed in ipset"
        ).is_equal_to(True)

        #IPTableTest
        log.info(f"Running IPTables test in node : {testNode.name}")
        assert_that(
            testIPTables(self, testNode, log)
        ).described_as(
            f"Azure Firewall Component Test Failed in IpTables"
        ).is_equal_to(True)

def testIPSet(self, node, log):

    result = node.execute("tdnf -y install ipset", sudo=True)
    if "done" not in result.stdout:
        log.info(f"IPSet test failed while install ipset failed with error : {result.stdout}")
    log.info("Installed ipset for testing, Adding new ip set")
    cmd = f"ipset create {self.IPSETNAME} hash:ip"
    log.info(f"Creating set named {cmd} in ipset")
    result = node.execute(cmd, sudo=True)
    cmd = f"ipset add {self.IPSETNAME} 8.8.8.8"
    log.info(f"Adding ip 8.8.8.8 in ipset {self.IPSETNAME} {cmd}")
    result = node.execute(cmd, sudo=True)
    log.info(f"Remove {self.IPSETTESTDELETERULES} and Add {self.IPSETTESTADDRULE} to block the outgoing traffic to 8.8.8.8")
    addIPTableRules(node, self.FILTERTABLE, self.IPSETTESTADDRULE, log)
    removeIPTableRules(node, self.IPSETTESTDELETERULES, log)
    log.info(f"Added IPTable Rule in OUTPUT Chain to block outgoing traffic to 8.8.8.8")
    log.info(f"Send ICMP traffic to destination 8.8.8.8 to verify whether traffic is blocked using ipset")    
    result = node.tools[Ping].ping_async(target="8.8.8.8", count=self.PACKETCOUNT, sudo=True)
    pingresult = result.wait_result()
    log.debug(f"ICMP traffic result for destination 8.8.8.8 : {pingresult.stdout} ")
    if "100% packet loss" not in pingresult.stdout:
        log.info("ICMP traffic is being allowed eventhough the IPTables rules has been added to drop it")
        return False
    return True

def testconntrack(self, node, log):
    
    result = node.execute("tdnf -y install conntrack", sudo=True)
    log.debug(f"Result for installing conntrack in node {node.name} : Result : {result.stdout}")
    if "done" not in result.stdout:
        log.info(f"Conntrack test failed while installing conntrack, failed with error: {result.stdout}")
        return False
    log.info("Installed conntrack for testing, Adding entry in conntrack ")
    cmd = f"conntrack -I -s {self.CONNMARKSRC} -d {self.CONNMARKDEST} --protonum {self.CONNMARKPROTO} --timeout {self.CONNMARKTIMEOUT} --mark={self.CONNMARKACTIVE}"
    log.info(f"Adding this entry {cmd} to conntrack")
    result = node.execute(cmd, sudo=True)
    log.debug(f'Result for adding conntrack entry : {result.stdout}')
    if "1 flow entries have been created" not in result.stdout:
        log.info(f"Failed in adding entry to conntrack, Result: {result.stdout}")
        return False
    log.info("Successfully added entry to conntrack, now update the entry")
    cmd = f"conntrack -U --mark 0/{self.CONNMARKACTIVE}"
    log.info(f"Update the conntrack entry with command : {cmd}")
    result = node.execute(cmd, sudo=True)
    if "flow entries have been updated" not in result.stdout:
        log.info(f"Failed in updating conntrack entry : {result.stdout}")
        return False
    return verifyConntrackEntry(node, self.CONNMARKSRC, self.CONNMARKDEST, self.CONNMARKPROTO, "0", log)

def testIPTables(self, node, log):
    log.info("Add Rules To PreRouting Chain and verify the iptables")
    createIPTableChain(node, self.NATTABLE, self.NATCHAIN, log)
    addIPTableRules(node, self.NATTABLE, self.PREROUTINGCHAIN, log)
    if not asyncio.run(verifyIPTables(ipTableDump(node, log), self.PREROUTINGCHAIN, log)):
       log.info("IPTables test failed in PreRouting Chain")
       return False
    log.info("Add Rules To Forwarad Chain and verify the iptables")
    createIPTableChain(node, self.FILTERTABLE, self.FILTERCHAIN, log)
    addIPTableRules(node, self.FILTERTABLE, self.FORWARDCHAIN, log)
    if not asyncio.run(verifyIPTables(ipTableDump(node, log), self.FORWARDCHAIN, log)):
        log.info("IPTables test failed in Forwarding Chain")
        return False
    return True

def addIPTableRules(node, ipTable, ipTableRules, log):
    for ipTableRule in ipTableRules:
        cmd = f"iptables -t {ipTable} {ipTableRule}"
        log.debug(f"Adding IP Table Rule {ipTableRule} to IPTables : {cmd}")
        node.execute(cmd, sudo=True)

def createIPTableChain(node, ipTable, ipTableChains, log):
    for ipTablechain in ipTableChains:
        cmd = f"iptables -t {ipTable} -N {ipTablechain}"
        log.debug(f"Creating new chain {ipTablechain} in IPTables : {cmd}")
        node.execute(cmd, sudo=True)

async def verifyIPTables(iptablesDump, arraytoMatch, log):
    iptables = iptablesDump.splitlines()
    for ipTableEntry in arraytoMatch:
        if ipTableEntry not in iptables:
            log.debug(f"Not matched  : {ipTableEntry}")
            return False
    return True

def ipTableDump(node, log):
    iptableumpResult = node.execute("iptables-save", sudo=True)
    log.debug(f"IPTable Dump Result : {iptableumpResult.stdout}")
    return iptableumpResult.stdout

def verifyConntrackEntry(node, clientNICIPAddr, serverNICIPAddr, protocol, mask, log):
    log.info(f"Verifying conntrack entry for Protocol {protocol} from {clientNICIPAddr} to {serverNICIPAddr} in node {node.name}")
    result = node.execute(f"bash -c \"conntrack -L | grep '{clientNICIPAddr}' | grep '{serverNICIPAddr}' | grep '{protocol}' | grep '{mask}'\"", sudo=True)
    if len(result.stdout.splitlines()) > 1:
        log.info("Conntrack Entry Found")
        return True
    else:
        return False
    
def removeIPTableRules(node, ipTableRules, log):
    for ipTableRule in ipTableRules:
        log.info(f"Removing rule {ipTableRule} from iptables")
        node.execute(f"iptables -D {ipTableRule}", sudo=True)