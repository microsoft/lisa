import asyncio
from typing import cast
from assertpy import assert_that
from lisa import (
    Environment,
    Logger,
    RemoteNode,
    TestSuite,
    TestSuiteMetadata,
    TestCaseMetadata,
    simple_requirement
)
from .azFWConstants import (
    NetworkRules,
    ComponentTestConstants
)
from .azfwUtility import (
    addIPTableRules,
    createIPTableChain,
    verifyIPTables,
    ipTableDump
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
        log.info(f"Running IPTables test in node : {testNode.name}")
        assert_that(
            testIPTables(testNode, log)
        ).described_as(
            f"Azure Firewall Component Test Failed in IpTables"
        ).is_equal_to(True)







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