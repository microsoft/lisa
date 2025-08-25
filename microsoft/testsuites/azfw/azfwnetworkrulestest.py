from typing import cast
import json
import asyncio
from retry import retry 
from assertpy import assert_that
from typing import TYPE_CHECKING
from .azfwUtility import (
    installAzureCLI,
    loginAzureCLI,
    enableKeyVaultVMExtension,
    enableNICIPForwarding,
    getResourceGroupName,
    downloadFilesFromBlob,
    deleteIPRoute,
    reloadRules,
    verifyIPTables,
    verifyConntrackEntry,
    ipv4_to_lpm,
    getNodesNICandIPaddr
)
from .azFWConstants import (
    ProtocolConstants,
    GenevaConfigurationConstants,
    TrafficConfigurations,
    ConnTrackMarks,
    VMConfigurations,
    StorageConfigurations,
    TCPProtocolConstants,
    ICMPProtocolConstants,
    UDPProtocolConstants,
    NetworkRules
)
# from lisa.sut_orchestrator.azure.common import add_user_assign_identity
from lisa import (
    Environment,
    Logger,
    RemoteNode,
    TestSuite,
    TestSuiteMetadata,
    TestCaseMetadata,
    simple_requirement,
)
from lisa.features import NetworkInterface
from lisa.tools import Ls, Mkdir, Iperf3, Ping
from lisa.tools import Ip as ip
from lisa.tools import Ping as ping
from lisa.tools import Sysctl as sysctl
from time import sleep
import re
from lisa.features import NetworkInterface
from lisa.sut_orchestrator.azure.common import (
    get_node_context,
)
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from string import Template
from azure.mgmt.network import NetworkManagementClient


@TestSuiteMetadata(
    area="azure-firewall",
    category="FirewallNetworkRuleTest",
    description="""
    This test suite will verify if the Azure Firewall is able to properly accept or reject traffic
    based on the network rules configured in the firewall. Firewall will be tested upon the following traffic types:
     - TCP, UDP, ICMP, ESP, Unknown
    """,
    requirement=simple_requirement(min_count=VMConfigurations.VMCOUNT, min_nic_count=VMConfigurations.NICCOUNT),
)


class AzureFirewallNetworkRuleTest(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case will verify if the Azure Firewall is able to properly process the network rules and
        configure the iptables rules accordingly and whether the fast path marking is done properly on the conntrack and
        verify if the conntrack mark is being set to zero back after rule refresh            
    """,
        priority=1,
    )


    def test_network_rules(self, environment: Environment, log: Logger) -> None:
    
        firewallNode, clientNode, serverNode, clientNICName, clientNICIPAddr, serverNICName, serverNICIPAddr, firewallNICName, firewallNICIPAddr = chooseFirewallServerClientVMs(environment, log)
     

        resourceGroupName = getResourceGroupName(firewallNode, log)
        log.info(f"Resource Group Name: {resourceGroupName}")

        #Create Route Table to route traffic via Firewall
        asyncio.run(createRouteTable(clientNode, serverNode, clientNICName, clientNICIPAddr, serverNICName, serverNICIPAddr, firewallNICIPAddr, log))

        #Enable IP Forwarding on the NICs in which packets are gonna be sent out
        asyncio.run(enableNICIPForwarding(firewallNode, firewallNICIPAddr, log))
        asyncio.run(enableNICIPForwarding(clientNode, clientNICIPAddr, log))
        asyncio.run(enableNICIPForwarding(serverNode, serverNICIPAddr, log))

        delFirewallNICRoutes(firewallNICIPAddr, firewallNode, log)
        # deleteIPRoute(firewallNode, firewallNICIPAddr, log)

        log.info("Enabling Key Vault VM Extension on Firewall Node to provision Geneva Certificates through Client Node")


        # enableKeyVaultVMExtension(clientNode, firewallResourceGroupName, firewallNode.name, GenevaConfigurationConstants.SETTINGSFILENAME, GenevaConfigurationConstants.SETTINGSFILEPATH, log)

        installAzureCLI(clientNode, log)
        loginAzureCLI(clientNode, StorageConfigurations.GSAMANAGEDIDENTITY, log)
        downloadFilesFromBlob(clientNode, GenevaConfigurationConstants.SETTINGSFILENAME, GenevaConfigurationConstants.SETTINGSFILEPATH, StorageConfigurations.LISASTORAGEACCOUNTNAME, StorageConfigurations.LISACONTAINERNAME, log)
        assert_that(
            enableKeyVaultVMExtension(clientNode, resourceGroupName, firewallNode.name, GenevaConfigurationConstants.SETTINGSFILENAME, GenevaConfigurationConstants.SETTINGSFILEPATH, StorageConfigurations.LISASTORAGEACCOUNTNAME, StorageConfigurations.LISACONTAINERNAME, log)
        ). described_as (
            f"Failed while Enabling Key Vault VM Extension in  node : {clientNode.name}"
        ).is_equal_to(1)

        extractKeyAndCerts(firewallNode, log)

        log.info("Setting up Azure Firewall in VM:",firewallNode.name)
        firewallInit(firewallNode, log)


        #Add iptable rules to accept traffic on the Server Side(n2)
        serverNode.execute("iptables -A INPUT -p tcp -j ACCEPT", sudo=True)
        serverNode.execute("iptables -A INPUT -p udp -j ACCEPT", sudo=True)
        serverNode.execute("iptables -A INPUT -p icmp -j ACCEPT", sudo=True)
        
        #Install iperf3 in both Client And Server Side
        serverNode.execute("sudo tdnf install -y iperf3", sudo=True)
        clientNode.execute("sudo tdnf install -y iperf3", sudo=True)

        result = firewallNode.execute("iptables-save", sudo=True)
        log.debug(f"IPTable Rules result {result.stdout}")

        assert_that(asyncio.run(verifyIPTables(result.stdout, NetworkRules.PREROUTINGCHAIN, log))).described_as(
            f"IPTABLE Rules are not configured properly in PreRouting chain"
        ).is_equal_to(True)

        assert_that(asyncio.run(verifyIPTables(result.stdout, NetworkRules.FORWARDCHAIN, log))).described_as(
            f"IPTABLE Rules are not configured properly in Forward chain"
        ).is_equal_to(True)

        testICMPTraffic(firewallNode, clientNode, clientNICName, clientNICIPAddr, serverNICIPAddr, log)
        testTCPUDPTraffic(firewallNode, clientNICName, clientNode, serverNode, serverNICIPAddr, clientNICIPAddr, str(TrafficConfigurations.IPERF3PORT), ProtocolConstants.TCP, TCPProtocolConstants.RULEFILENAME, log)
        sleep(10)
        testTCPUDPTraffic(firewallNode, clientNICName, clientNode, serverNode, serverNICIPAddr, clientNICIPAddr, str(TrafficConfigurations.IPERF3PORT), ProtocolConstants.UDP, UDPProtocolConstants.RULEFILENAME, log)


def testICMPTraffic(firewallNode, clientNode, clientNICName, clientNICIPAddr, serverNICIPAddr,log):
    log.info("Generating ICMP Traffic")


    assert_that(generateTraffic(clientNode, "", ProtocolConstants.ICMP, "", clientNICIPAddr, clientNICName, serverNICIPAddr, log)).described_as(
        f"Failed to generate {ProtocolConstants.ICMP} traffic from {clientNICIPAddr} to {serverNICIPAddr} in node {clientNode.name}"
    ).is_equal_to(1)


    log.info(f"Verifying Conntrack Entry for ICMP with mark {ConnTrackMarks.ACTIVE}")
    assert_that(verifyConntrackEntry(firewallNode, clientNICIPAddr, serverNICIPAddr, ProtocolConstants.ICMP, ConnTrackMarks.ACTIVE, log)).described_as(
        f"Failed to find conntrack entry for {ProtocolConstants.ICMP} traffic from {clientNICIPAddr} to {serverNICIPAddr} in node {firewallNode.name} with mask {ConnTrackMarks.ACTIVE}"
    ).is_equal_to(1)


    log.info(f"Reloading Firewall Rules {ICMPProtocolConstants.RULEFILENAME}")


    assert_that(reloadRules(firewallNode, ICMPProtocolConstants.RULEFILENAME, StorageConfigurations.GSAMANAGEDIDENTITY, log)).described_as(
        f"Firewall Rules Reload Failed for {ProtocolConstants.ICMP} while using ruleConfig {ICMPProtocolConstants.RULEFILENAME}"        
    )

    log.info(f"Verifying Conntrack Entry for ICMP with mark {ConnTrackMarks.RESET} after reloading firewall rules")
    assert_that(verifyConntrackEntry(firewallNode, clientNICIPAddr, serverNICIPAddr, ProtocolConstants.ICMP, ConnTrackMarks.RESET, log)).described_as(
        f"Failed to find conntrack entry for {ProtocolConstants.ICMP} traffic from {clientNICIPAddr} to {serverNICIPAddr} in node {firewallNode.name} with mask {ConnTrackMarks.RESET}"
    ).is_equal_to(1)


    result = firewallNode.execute(f"iptables-save",sudo=True)
    log.debug(f"IPTables Dump after reloading rules in protocol {ProtocolConstants.ICMP}: {result.stdout}")

    assert_that(asyncio.run(verifyIPTables(result.stdout, ICMPProtocolConstants.PREROUTINGCHAIN, log))).described_as(
        f"IPTABLE Rules are not configured properly for protocol {ProtocolConstants.ICMP} in PreRouting chain"
    ).is_equal_to(True)

    assert_that(asyncio.run(verifyIPTables(result.stdout, ICMPProtocolConstants.FORWARDCHAIN, log))).described_as(
        f"IPTABLE Rules are not configured properly for protocol {ProtocolConstants.ICMP} in Forward chain"
    ).is_equal_to(True)

    assert_that(generateTraffic(clientNode, "", ProtocolConstants.ICMP, "", clientNICIPAddr, clientNICName, serverNICIPAddr, log)).described_as(
        f"Failed to generate {ProtocolConstants.ICMP} traffic from {clientNICIPAddr} to {serverNICIPAddr} in node {clientNode.name}"
    ).is_equal_to(1)

    assert_that(verifyConntrackEntry(firewallNode, clientNICIPAddr, serverNICIPAddr, ProtocolConstants.ICMP, ConnTrackMarks.ACTIVE, log)).described_as(
        f"Failed to find conntrack entry for {ProtocolConstants.ICMP} traffic from {clientNICIPAddr} to {serverNICIPAddr} in node {firewallNode.name} with mask {ConnTrackMarks.ACTIVE}"
    ).is_equal_to(1)



def generateTraffic(clientNode, serverNode, protocol, port, clientNICIPAddr, clientNICName, serverNICIPAddr, log):
    if protocol == ProtocolConstants.TCP or protocol == ProtocolConstants.UDP:
        log.info(f"Generating {protocol} Traffic from {clientNICIPAddr} to {serverNICIPAddr}, total packet count:{TrafficConfigurations.PACKETCOUNT}")
        asyncio.run(setupServer(serverNode, port, serverNICIPAddr, log))
        sleep(10)
        result = setupClient(clientNode, port, serverNICIPAddr, clientNICIPAddr, str(TrafficConfigurations.PACKETLENGTH), str(TrafficConfigurations.TOTALBYTES), protocol, str(TrafficConfigurations.BITRATE), log)
        return result
    elif protocol == ProtocolConstants.ICMP:
        log.info(f"Generating ICMP Traffic from {clientNICIPAddr} to {serverNICIPAddr}, total packet count:{TrafficConfigurations.PACKETCOUNT}")
        icmpResult = clientNode.tools[Ping].ping_async(target=serverNICIPAddr, nic_name=clientNICName, count=TrafficConfigurations.PACKETCOUNT, sudo=True)
        icmpResult = icmpResult.wait_result()
        log.debug(f"Result for Generating {protocol} Traffic : {icmpResult.stdout}")
        if "packets transmitted, " in icmpResult.stdout:
            return 1
        else:
            return 0


async def setupServer(node, serverPort, serverNICIPAddr, log):
    servercmd = f"iperf3 -s -p {serverPort} -B {serverNICIPAddr} --one-off -D"
    log.info(f"Server Command : {servercmd}")
    result = node.execute(servercmd)
    log.info(f"Result for Running the Server in IPAddress {serverNICIPAddr} : {result.stdout}")


@retry(tries=5, delay=2)
def setupClient(node, destionationPort, destinationIPAddr, clientNICIPAddr, bufferLength, numberOfBytes, protocol, bitRate, log):
    if protocol == ProtocolConstants.UDP:
        clientcmd = f"iperf3 -c {destinationIPAddr} -p {destionationPort} -B {clientNICIPAddr} -u"
    elif protocol == ProtocolConstants.TCP:
        clientcmd = f"iperf3 -c {destinationIPAddr} -p {destionationPort} -B {clientNICIPAddr} -l {bufferLength} -n {numberOfBytes}"
    log.info(f"Client Command : {clientcmd}")
    result = node.execute(clientcmd)
    log.info(f"Result for Running the Client in IPAddress {clientNICIPAddr} : {result.stdout}")
    if "iperf Done." in result.stdout:
        return 1
    elif "iperf3: error" in result.stdout:
        return 0


def testTCPUDPTraffic(firewallNode,clientNICName, clientNode,serverNode,serverNICIPAddr,clientNICIPAddr,port, protocol, ruleFileName, log):

    if protocol == ProtocolConstants.TCP:
        forwardChain = TCPProtocolConstants.FORWARDCHAIN
        preRoutingChain = TCPProtocolConstants.PREROUTINGCHAIN
    elif protocol == ProtocolConstants.UDP:
        forwardChain = UDPProtocolConstants.FORWARDCHAIN
        preRoutingChain = UDPProtocolConstants.PREROUTINGCHAIN  


    log.info(f"Sending {protocol} Traffic from {clientNICIPAddr} to {serverNICIPAddr} on port {port}")
    assert_that(generateTraffic(clientNode, serverNode, protocol, port, clientNICIPAddr, clientNICName, serverNICIPAddr, log)).described_as(
        f"Failed to generate {protocol} traffic from {clientNICIPAddr} to {serverNICIPAddr}"
    ).is_equal_to(1)
    

    assert_that(verifyConntrackEntry(firewallNode, clientNICIPAddr, serverNICIPAddr, protocol, ConnTrackMarks.ACTIVE, log)).described_as(
        f"Failed to find conntrack entry for {protocol} traffic from {clientNICIPAddr} to {serverNICIPAddr} in node {firewallNode.name} with mask {ConnTrackMarks.ACTIVE}"
    ).is_equal_to(1)


    log.info(f"Reloading Firewall Rules {ruleFileName}")
    assert_that(reloadRules(firewallNode, ruleFileName, StorageConfigurations.GSAMANAGEDIDENTITY, log)).described_as(
        f"Firewall Rules Reload Failed for {protocol} while using ruleConfig {ruleFileName}"
    ).is_equal_to(1)

    result = firewallNode.execute(f"iptables-save",sudo=True)
    log.debug(f"After Reloading Rules IPTable Result: {result.stdout}")

    assert_that(asyncio.run(verifyIPTables(result.stdout, preRoutingChain, log))).described_as(
        f"IPTABLE Rules are not configured properly for protocol {protocol} in PreRouting chain"
    ).is_equal_to(True)

    assert_that(asyncio.run(verifyIPTables(result.stdout, forwardChain, log))).described_as(
        f"IPTABLE Rules are not configured properly for protocol {protocol} in Forward chain"
    ).is_equal_to(True)


    assert_that(verifyConntrackEntry(firewallNode, clientNICIPAddr, serverNICIPAddr, protocol, ConnTrackMarks.RESET, log)).described_as(
        f"Failed to find conntrack entry for {protocol} traffic from {clientNICIPAddr} to {serverNICIPAddr} in node {firewallNode.name} with mask {ConnTrackMarks.RESET}"
    ).is_equal_to(1)

    assert_that(generateTraffic(clientNode, serverNode, protocol, port, clientNICIPAddr, clientNICName, serverNICIPAddr, log)).described_as(
        f"Failed to generate {protocol} traffic from {clientNICIPAddr} to {serverNICIPAddr} after reloading firewall Rules"
    ).is_equal_to(1)

    assert_that(verifyConntrackEntry(firewallNode, clientNICIPAddr, serverNICIPAddr, protocol, ConnTrackMarks.ACTIVE, log)).described_as(
        f"Failed to find conntrack entry for {protocol} traffic from {clientNICIPAddr} to {serverNICIPAddr} in node {firewallNode.name} with mask {ConnTrackMarks.ACTIVE}"
    ).is_equal_to(1)

  

def extractKeyAndCerts(node, log):
    #Get all the files in /tmp/ directory and loop through them, find and move the .pem file to /var/lib/waagent
    result = node.execute("ls /var/lib/waagent/", sudo=True)
    log.info(f"Files in /tmp/: {result.stdout.splitlines()}")
    for file in result.stdout.splitlines():
        if file.startswith("lisatestgenevakv.geneva2.") and file.endswith(".PEM"):
            pemFileName = file
            log.info(f"Found .PEM file: {pemFileName}")
            node.execute(f"mv /tmp/{file} /var/lib/waagent/", sudo=True)
            log.info(f"Moved {file} to /var/lib/waagent/")
            break

    log.info("Move the .PEM file from /tmp/ to /var/lib/waagent")
    # Extract the key and certificates from the .pem file
    pemFilePath = f"/var/lib/waagent/{pemFileName}"
    result = node.execute (f"openssl pkey -in {pemFilePath} -out {pemFilePath.replace('.PEM', '.prv')}", sudo=True)
    log.info(f"Extracted private key from {pemFilePath} to {pemFilePath.replace('.PEM', '.prv')}", result.stdout)
    result = node.execute(f"openssl x509 -in {pemFilePath} -out {pemFilePath.replace('.PEM', '.crt')}", sudo=True)
    log.info(f"Extracted certificate from {pemFilePath} to {pemFilePath.replace('.PEM', '.crt')}", result.stdout)
    result = node.execute(f"openssl x509 -in {pemFilePath.replace('.PEM', '.crt')} -text -noout", sudo=True)
    log.info(f"Extracted certificate details from {pemFilePath.replace('.PEM', '.crt')}", result.stdout)

async def createRouteTable(clientNode, serverNode, clientNICName, clientNICIPAddr, serverNICName, serverNICIPAddr, firewallNICIPAddr, log):
    log.info("Creating Route Table to send traffic via Azure Firewall Client --> Firewall --> Server")

    routeTableName = f"{clientNICName}-clientToFirewall-route_table"
    log.info(f"Creating Client Route Table: {clientNICName}/{clientNICIPAddr}/32 to Firewall: {firewallNICIPAddr} and Client Subnet: {ipv4_to_lpm(clientNICIPAddr)}")
    clientNode.features[NetworkInterface].create_route_table(
        nic_name= clientNICName,
        route_name= "clientToFirewall",
        subnet_mask= ipv4_to_lpm(clientNICIPAddr),
        em_first_hop= clientNICIPAddr+"/32",
        next_hop_type= "VirtualAppliance",
        dest_hop= firewallNICIPAddr
    )

    log.info(f"Creating Server Route Table: {serverNICName}/{serverNICIPAddr}/32 to Firewall: {firewallNICIPAddr} and Server Subnet: {ipv4_to_lpm(serverNICIPAddr)}")
    serverNode.features[NetworkInterface].add_route_to_table(
        route_name= "serverToFirewall",
        subnet_mask= ipv4_to_lpm(serverNICIPAddr),
        em_first_hop= serverNICIPAddr+"/32",
        next_hop_type= "VirtualAppliance",
        dest_hop= firewallNICIPAddr,
        routeTableName= routeTableName
    )

# Allocating the VMs to Firewall, Client and Server and choosing the correct NIC and making sure that Client and Server NICs are in same Subnet but not in same subnet as Firewalll NIC
def chooseFirewallServerClientVMs(environment, log):
    # Node 0: Firewall
    firewallNode = cast(RemoteNode, environment.nodes[0])
    firewallNIC = firewallNode.nics.get_nic_by_index(0)
    firewallNICName = firewallNIC.name
    firewallNICIPAddr = firewallNIC.ip_addr
    fw_subnet = ".".join(firewallNICIPAddr.split(".")[:3])
    log.info(f"Firewall Node: {firewallNode.name}, NIC: {firewallNICName}, IP Address: {firewallNICIPAddr}")

    # Node 1: Client (NIC 0 not in same subnet as firewall)
    clientNode = cast(RemoteNode, environment.nodes[1])
    clientNIC = None
    clientNICName = ""
    clientNICIPAddr = ""
    availableNICs, availableNICsIPaddr = getNodesNICandIPaddr(clientNode, VMConfigurations.NICCOUNT, log)
    for i in range(VMConfigurations.NICCOUNT):
        nic = availableNICsIPaddr[i]
        client_subnet = ".".join(nic.split(".")[:3])
        if client_subnet != fw_subnet:
            clientNICName = availableNICs[i]
            clientNICIPAddr = availableNICsIPaddr[i]
            log.info(f"Client Node: {clientNode.name}, NIC: {clientNICName}, IP Address: {clientNICIPAddr}")
            break

    # Node 2: Server (Choose NIC which is in same subnet as Client)
    serverNode = cast(RemoteNode, environment.nodes[2])
    availableNICs, availableNICsIPaddr = getNodesNICandIPaddr(serverNode, VMConfigurations.NICCOUNT, log)
    for i in range(VMConfigurations.NICCOUNT):
        nic = availableNICsIPaddr[i]
        server_subnet = ".".join(nic.split(".")[:3])
        if server_subnet == client_subnet:
            serverNICName = availableNICs[i]
            serverNICIPAddr = availableNICsIPaddr[i]
            log.info(f"Server Node: {serverNode.name}, NIC: {serverNICName}, IP Address: {serverNICIPAddr}")
            break

    return firewallNode, clientNode, serverNode, clientNICName, clientNICIPAddr, serverNICName, serverNICIPAddr, firewallNICName, firewallNICIPAddr



def delFirewallNICRoutes(firewallNICIPAddr,firewallNode, log):

    log.info("Deleting Azure Firewall's NIC routes")

    #GET the NICs and their IP addresses
    firewallNICs, firewallNICsIPaddr = getNodesNICandIPaddr(firewallNode, VMConfigurations.NICCOUNT, log)
    log.info(f"Firewall NICs: {firewallNICs}, Firewall NICs IP addresses: {firewallNICsIPaddr}")

    deletenicroutes = []
    #Delete the routes for NIC 1 and NIC 2
    for ipaddr in firewallNICsIPaddr:
        if ipaddr not in firewallNICIPAddr:
            deletenicroutes.append(ipaddr)

    deleteIPRoute(firewallNode, deletenicroutes, log)

    firewallRoutes = firewallNode.execute("ip route show", sudo=True)
    log.info(f"Routes after deletion: {firewallRoutes}")


def firewallInit(firewallNode, log):
    firewallNode.execute("sudo tdnf install -y azure-cli", sudo=True)

    result = firewallNode.execute(f"az login --identity --resource-id {StorageConfigurations.GSAMANAGEDIDENTITY}")
    log.info('Successfully logged into lisa storage', result)
    
    #download necessary files from blob storage
    files = ["mdsd.service", "mock_statsd.service", "mock_statsd.py", "mock_mdsd", "install_runtime_deps.sh", "importdatafromjson.py", "cseparams.json", "bootstrap_geneva.sh"]
    for file in files:
        firewallNode.execute(f"az storage blob download --auth-mode login --account-name lisatestresourcestorage  -c fwcreateconfigfiles -n {file} -f /tmp/{file}")

    result = firewallNode.execute("chmod 666 /tmp/mdsd.service /tmp/mock_statsd.service /tmp/mock_statsd.py /tmp/mock_mdsd /tmp/install_runtime_deps.sh /tmp/importdatafromjson.py bootstrap_geneva.sh", sudo=True)
    result = firewallNode.execute("chmod -R 777 /tmp/mdsd.service /tmp/mock_statsd.service /tmp/mock_statsd.py /tmp/mock_mdsd /tmp/install_runtime_deps.sh /tmp/importdatafromjson.py bootstrap_geneva.sh", sudo=True)

    #Generate mdsMetadata.txt file
    result = firewallNode.execute("python3 /tmp/importdatafromjson.py", sudo=True)
    log.info("Successfully generated mdsMetadata.txt", result)
    #Upload the mdsMetadata.txt file to blob storage
    result = firewallNode.execute("az storage blob upload --auth-mode login --account-name lisatestresourcestorage  -c fwcreateconfigfiles -n mdsMetadata.txt -f /tmp/mdsMetadata.txt", sudo=True) # Done 
    log.info("Successfully uploaded mdsMetadata.txt to blob storage", result) # Done

    result = firewallNode.execute("bash -x /tmp/install_runtime_deps.sh", sudo=True)
    log.info("Successfully executed install_runtime_deps.sh", result.stdout)
    firewallNode.execute("useradd -M -e 2100-01-01 azfwuser", sudo=True)
    

    result = firewallNode.execute(f"az storage blob download --auth-mode login --account-name {StorageConfigurations.GSASTORAGEACCOUNTNAME} -c {StorageConfigurations.GSACONTAINERNAME} -n {StorageConfigurations.BOOTSTRAPFILENAME} -f /tmp/bootstrap.tar") #Done
    log.info("Successfully downloaded bootstrap.tar", result) #Done

    result = firewallNode.execute("sudo chmod 666 /tmp/bootstrap.tar", sudo=True) #Done
    log.info("Changed permissions for bootstrap.tar", result) #Done

    result = firewallNode.execute("sudo chmod -R 777 /tmp/bootstrap.tar", sudo=True) #Done
    log.info("Changed permissions for bootstrap.tar", result) #Done


    result = firewallNode.execute("mkdir /tmp/bootstrap/") #Done
    log.info("Created Directory /tmp/bootstrap/", result)

    result = firewallNode.execute("python -m ensurepip", sudo=True) #done
    log.info("Successfully installed psutil", result)
    result = firewallNode.execute('export PATH="$PATH:/home/lisatest/.local/bin"') #done
    log.info("Added /home/lisatest/.local/bin to PATH", result)
    result = firewallNode.execute(" python -m pip install psutil", sudo=True) #Done
    log.info("Successfully installed psutil", result)

    result = firewallNode.execute("tar -xvf /tmp/bootstrap.tar -C /tmp/bootstrap/", sudo=True) #Done
    log.info("Successfully extracted bootstrap.tar")


    json_value = {
            "RULE_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/ruleConfig.json",
            "RULE_CONFIG_NAME": "a36eb125-41ee-4e34-8158-c14c0c75ee4a",
            "SETTINGS_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/mdsMetadata.txt",
            "GENEVATHUMBPRINT": "3BD30EA445312E57C4C2AD1152524BE5D35E3937",
            "FQDN_TAGS_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/defaultfqdntags.json",
            "SERVICE_TAGS_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/servicetags.json",
            "WEB_CATEGORIES_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/defaultwebcategories.json",
            "IDPS_RULES_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/rules.tar.gz",
            "IDPS_RULES_OVERRIDES_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/instrusionsystemoverrides.json",
            "INTERFLOW_KEY": "c70e2937d7984d41bab046ad131fcbe0",
            "WEB_CATEGORIZATION_VENDOR_LICENSE_KEY": "7gk92m7cNiKmFtfkjwPua64zEVk2ct7z",
            "AAD_TENANT_ID": "33e01921-4d64-4f8c-a055-5bdaffd5e33d",
            "AAD_CLIENT_ID": "074a0fa4-34df-493f-985b-d3dedb49748b",
            "AAD_SECRET": "LZJeyEbkqM0Z+6B]l65ucj=WK-P@7d]*",
            "NUMBER_PUBLIC_IPS": 1,
            "NUMBER_PORTS_PER_PUBLIC_IP": 2496,
            "DATA_SUBNET_PREFIX": "10.0.0.0/24",
            "DATA_SUBNET_PREFIX_IPV6": "",
            "MGMT_SUBNET_PREFIX": "",
            "ROUTE_SERVICE_CONFIG_URL": None,
            "TENANT_KEYVAULT_URL": "https://fwcreationkeyvault.vault.azure.net/",
            "TENANT_IDENTITY_RESOURCE_ID": f"{StorageConfigurations.GSAMANAGEDIDENTITY}",
            "REGIONAL_KEYVAULT_URL": "https://fwcreationkeyvault.vault.azure.net/",
            "REGIONAL_IDENTITY_RESOURCE_ID": f"{StorageConfigurations.GSAMANAGEDIDENTITY}",
            "NOSNAT_IPPREFIXES_CONFIG_SAS_URL": None,
            "NOSNAT_IS_AUTO_LEARN_ENABLED": None
        }

    json_str = json.dumps(json_value)
    # escaped_json = json_str.replace('"', '\\"')
    command = f"/tmp/bootstrap/drop/vmss/bootstrap.sh '{json_str}'"
    result = firewallNode.execute(f"bash -x {command}", sudo=True)
    log.debug("Result for executing", result.stdout)
    if "Bootstrap complete.. exiting" in result.stdout:
        return 1
    else:
        return 0