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
from .constants import (
    NetworkRules,
    ComponentTestConstants,
    TrafficConfigurations
)
from .utility import (
    addIPTableRules,
    createIPTableChain,
    verifyIPTables,
    ipTableDump,
    verifyConntrackEntry,
    removeIPTableRules
)


@TestSuiteMetadata(
    area="azure-firewall",
    category="FirewallComponentTest",
    description="""
    This test suite will verify all the components that is being used by Azure Firewall Features
    """,
    requirement=simple_requirement(min_count=ComponentTestConstants.VMCOUNT, min_nic_count=ComponentTestConstants.NICCOUNT),

)


class AzureFirewallComponentTest(TestSuite):
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
            testconntrack(testNode,log)
        ). described_as(
            f"Azure Firewall Component Test failed in connmark"
        ).is_equal_to(1)

        #ipset test
        log.info(f"Running ipset test in node : {testNode.name}")
        assert_that(
            testIPSet(testNode, log)
        ).described_as(
            f"Azure Firewall Component test failed in ipset"
        ).is_equal_to(1)

        #IPTableTest
        log.info(f"Running IPTables test in node : {testNode.name}")
        assert_that(
            testIPTables(testNode, log)
        ).described_as(
            f"Azure Firewall Component Test Failed in IpTables"
        ).is_equal_to(True)





def testIPSet(node, log):

    result = node.execute("tdnf -y install ipset", sudo=True)
    if "done" not in result.stdout:
        log.info(f"IPSet test failed while install ipset failed with error : {result.stdout}")
    log.info("Installed ipset for testing, Adding new ip set")
    cmd = f"ipset create {ComponentTestConstants.IPSETNAME} hash:ip"
    log.info(f"Creating set named {cmd} in ipset")
    result = node.execute(cmd, sudo=True)
    cmd = f"ipset add {ComponentTestConstants.IPSETNAME} 8.8.8.8"
    log.info(f"Adding ip 8.8.8.8 in ipset {ComponentTestConstants.IPSETNAME} {cmd}")
    result = node.execute(cmd, sudo=True)
    log.info(f"Remove {ComponentTestConstants.IPSETTESTDELETERULES} and Add {ComponentTestConstants.IPSETTESTADDRULE} to block the outgoing traffic to 8.8.8.8")
    addIPTableRules(node, ComponentTestConstants.FILTERTABLE, ComponentTestConstants.IPSETTESTADDRULE, log)
    removeIPTableRules(node, ComponentTestConstants.IPSETTESTDELETERULES, log)
    log.info(f"Added IPTable Rule in OUTPUT Chain to block outgoing traffic to 8.8.8.8")
    log.info(f"Send ICMP traffic to destination 8.8.8.8 to verify whether traffic is blocked using ipset")    
    result = node.tools[Ping].ping_async(target="8.8.8.8", count=TrafficConfigurations.PACKETCOUNT, sudo=True)
    pingresult = result.wait_result()
    log.debug(f"ICMP traffic result for destination 8.8.8.8 : {pingresult.stdout} ")
    if "100% packet loss" not in pingresult.stdout:
        log.info("ICMP traffic is being allowed eventhough the IPTables rules has been added to drop it")
        return 0
    return 1


def testconntrack(node, log):
    
    result = node.execute("tdnf -y install conntrack", sudo=True)
    log.debug(f"Result for installing conntrack in node {node.name} : Result : {result.stdout}")
    if "done" not in result.stdout:
        log.info(f"Conntrack test failed while installing conntrack, failed with error: {result.stdout}")
        return 0
    log.info("Installed conntrack for testing, Adding entry in conntrack ")
    cmd = f"conntrack -I -s {ComponentTestConstants.CONNMARKSRC} -d {ComponentTestConstants.CONNMARKDEST} --protonum {ComponentTestConstants.CONNMARKPROTO} --timeout {ComponentTestConstants.CONNMARKTIMEOUT} --mark={ComponentTestConstants.CONNMARKACTIVE}"
    log.info(f"Adding this entry {cmd} to conntrack")
    result = node.execute(cmd, sudo=True)
    log.debug(f'Result for adding conntrack entry : {result.stdout}')
    if "1 flow entries have been created" not in result.stdout:
        log.info(f"Failed in adding entry to conntrack, Result: {result.stdout}")
        return 0
    log.info("Successfully added entry to conntrack, now update the entry")
    cmd = f"conntrack -U --mark 0/{ComponentTestConstants.CONNMARKACTIVE}"
    log.info(f"Update the conntrack entry with command : {cmd}")
    result = node.execute(cmd, sudo=True)
    if "flow entries have been updated" not in result.stdout:
        log.info(f"Failed in updating conntrack entry : {result.stdout}")
        return 0
    return verifyConntrackEntry(node, ComponentTestConstants.CONNMARKSRC, ComponentTestConstants.CONNMARKDEST, ComponentTestConstants.CONNMARKPROTO, "0", log)



def testIPTables(node, log):
    log.info("Add Rules To PreRouting Chain and verify the iptables")
    createIPTableChain(node, ComponentTestConstants.NATTABLE, ComponentTestConstants.NATCHAIN, log)
    addIPTableRules(node, ComponentTestConstants.NATTABLE, NetworkRules.PREROUTINGCHAIN, log)
    if not asyncio.run(verifyIPTables(ipTableDump(node, log), NetworkRules.PREROUTINGCHAIN, log)):
       log.info("IPTables test failed in PreRouting Chain")
       return False
    log.info("Add Rules To Forwarad Chain and verify the iptables")
    createIPTableChain(node, ComponentTestConstants.FILTERTABLE, ComponentTestConstants.FILTERCHAIN, log)
    addIPTableRules(node, ComponentTestConstants.FILTERTABLE, NetworkRules.FORWARDCHAIN, log)
    if not asyncio.run(verifyIPTables(ipTableDump(node, log), NetworkRules.FORWARDCHAIN, log)):
        log.info("IPTables test failed in Forwarding Chain")
        return False
    return True