from typing import cast
import json
import asyncio
from typing import TYPE_CHECKING
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
    get_network_client
)
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from string import Template
from azure.mgmt.network import NetworkManagementClient

#Constants
vmcount = 3
niccount = 3
gsaManagedIdentity = "/subscriptions/e7eb2257-46e4-4826-94df-153853fea38f/resourcegroups/gsatestresourcegroup/providers/Microsoft.ManagedIdentity/userAssignedIdentities/gsateststorage-blobreader"
lisaStorageAccountName = "lisatestresourcestorage"
lisaContainerName = "fwcreateconfigfiles"
firewallAppVersion = "app-15432201"
bootstrapFileName = f"app/{firewallAppVersion}/bootstrap.tar"
gsaContainerName = "app"
gsaMSIClientID = "6f5a4b4b-8ca9-47b8-a65b-50b249dafa6b"
gsaStorageAccountName = "gsateststorage"
cseparams = {
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
        "TENANT_IDENTITY_RESOURCE_ID": "/subscriptions/11764614-ffac-4e4d-8506-bdf64388ce6c/resourcegroups/Bala-LisaTestResourcesRG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/lisatestaccessidentity",
        "REGIONAL_KEYVAULT_URL": "https://fwcreationkeyvault.vault.azure.net/",
        "REGIONAL_IDENTITY_RESOURCE_ID": "/subscriptions/11764614-ffac-4e4d-8506-bdf64388ce6c/resourcegroups/Bala-LisaTestResourcesRG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/lisatestaccessidentity",
        "NOSNAT_IPPREFIXES_CONFIG_SAS_URL": None,
        "NOSNAT_IS_AUTO_LEARN_ENABLED": None
    }

#Templates
imcpClientTemplate = Template("ping -c $count -I $NICName $destinationIPAddr -i $interval")
tcpClientTemplate = Template("iperf3 -V -c $destinationIPAddr --port $port -B $NICIPAddr -t $testDuration")
tcpServerTemplate = Template("iperf3 -s -B $NICIPAddr -p $destinationPort --one-off")
udpClientTemplate = Template("iperf3 -V -c $destinationIPAddr --port $port -B $NICIPAddr -t $testDuration -u")
udpRuleConfigName = "allowUDPConfig.json"



@TestSuiteMetadata(
    area="azure-firewall",
    category="FirewallNetworkRuleTest",
    description="""
    This test suite will verify if the Azure Firewall is able to properly accept or reject traffic
    based on the network rules configured in the firewall. Firewall will be tested upon the following traffic types:
     - TCP, UDP, ICMP, ESP, Unknown
    """,
    requirement=simple_requirement(min_count=vmcount, min_nic_count=niccount),
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

        #Enable IP Forwarding
        firewallNode.tools[sysctl].write("net.ipv4.ip_forward", "1")
        clientNode.tools[sysctl].write("net.ipv4.ip_forward", "1")
        serverNode.tools[sysctl].write("net.ipv4.ip_forward", "1")        

        firewallNodeContext = get_node_context(firewallNode)
        firewallResourceGroupName = firewallNodeContext.resource_group_name

        #Create Route Table to route traffic via Firewall
        asyncio.run(createRouteTable(clientNode, serverNode, clientNICName, clientNICIPAddr, serverNICName, serverNICIPAddr, firewallNICIPAddr, log))

        #Enable IP Forwarding on the NICs in which packets are gonna be sent out
        asyncio.run(enableNICIPForwarding(firewallNode, firewallNICIPAddr, log))
        asyncio.run(enableNICIPForwarding(clientNode, clientNICIPAddr, log))
        asyncio.run(enableNICIPForwarding(serverNode, serverNICIPAddr, log))

        delFirewallNICRoutes(firewallNICIPAddr, firewallNode, log)

        log.info("Enabling Key Vault VM Extension on Firewall Node to provision Geneva Certificates through Client Node")
        enableKeyVaultVMExtension(clientNode, firewallResourceGroupName, firewallNode.name, "settings.json", "/tmp/settings.json", log)
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

        testICMPTraffic(firewallNode, clientNode, clientNICName, clientNICIPAddr, serverNICIPAddr, log)
        testTCPUDPTraffic(firewallNode, clientNICName, clientNode, serverNode, serverNICIPAddr, clientNICIPAddr, 5201, "tcp", log)
        testTCPUDPTraffic(firewallNode, clientNICName, clientNode, serverNode, serverNICIPAddr, clientNICIPAddr, 5201, "udp", log)


async def enableNICIPForwarding(node, nodeNICIPAddr, log):
    log.info(f"Enable IP Forwarding for IP Addr : {nodeNICIPAddr}")
    result = node.features[NetworkInterface].switch_ip_forwarding(enable=True, private_ip_addr=nodeNICIPAddr)

def testICMPTraffic(firewallNode, clientNode, clientNICName, clientNICIPAddr, serverNICIPAddr,log):
    protocol = "icmp"
    log.info("Generating ICMP Traffic")
    icmpresult = generateTraffic(clientNode, "", protocol, clientNICIPAddr, clientNICName, serverNICIPAddr, log)
    verifyConntrackEntry(firewallNode, clientNICIPAddr, serverNICIPAddr, protocol, "256", log)
    result = firewallNode.execute(f"iptables-save",sudo=True)
    log.info(f"Before Reloading Rules IPTable Result : {result.stdout}")
    log.info(f"ICMP Traffic Result before reload : {icmpresult.stdout}")
    log.info(f"Reloading Firewall Rules {udpRuleConfigName}")
    reloadRules(firewallNode, udpRuleConfigName, log)
    log.info(f"IPTable Rules : {result.stdout}")
    verifyConntrackEntry(firewallNode, clientNICIPAddr, serverNICIPAddr, protocol, "0", log)
    icmpresult = generateTraffic(clientNode, "", protocol, clientNICIPAddr, clientNICName, serverNICIPAddr, log)
    log.info(f"ICMP Traffic Result after reload : {icmpresult.stdout}")
    verifyConntrackEntry(firewallNode, clientNICIPAddr, serverNICIPAddr, protocol, "256", log)


def verifyConntrackEntry(firewallNode, clientNICIPAddr, serverNICIPAddr, protocol, mask, log):
    
    log.info(f"Verifying conntrack entry for Protocol {protocol} from {clientNICIPAddr} to {serverNICIPAddr} in node {firewallNode.name}")
    result = firewallNode.execute(f"bash -c \"conntrack -L | grep '{clientNICIPAddr}' | grep '{serverNICIPAddr}' | grep '{protocol}' | grep '{mask}'\"", sudo=True)
    if result.stdout:
        log.info(f"Found entry for protocol {protocol} from {clientNICIPAddr} to {serverNICIPAddr} \n {result.stdout}")
    

def generateTraffic(clientNode, serverNode, protocol, clientNICIPAddr, clientNICName, serverNICIPAddr, log):

    packetCount = 40
    packetLength = 128000
    totalBytes = packetCount*packetLength
    bitRate = f"{(packetLength * 8) / (1024*1024)}M/{packetCount}"
    port = 5201

    if protocol == "tcp":
        log.info(f"Generating TCP Traffic from {clientNICIPAddr} to {serverNICIPAddr}, total packet count:{packetCount}")
        # serverProcess = serverNode.tools[Iperf3].run_as_server_async(port=port, one_connection_only=True, bind=serverNICIPAddr, daemon=False)
        # clientProcess = clientNode.tools[Iperf3].run_as_client_async(server_ip=serverNICIPAddr,port=port,client_ip=clientNICIPAddr,buffer_length= packetLength, numberofBytes=totalBytes)
        # client_result = clientProcess.wait_result(timeout=20)
        # server_result = serverProcess.wait_result(timeout=20)
        asyncio.run(setupServer(serverNode, port, serverNICIPAddr, log))
        sleep(10)
        setupClient(clientNode, port, serverNICIPAddr, clientNICIPAddr, str(packetLength), str(totalBytes), False, "", log)
    elif protocol == "icmp":
        log.info(f"Generating ICMP Traffic from {clientNICIPAddr} to {serverNICIPAddr}, total packet count:{packetCount}")
        icmpResult = clientNode.tools[Ping].ping_async(target=serverNICIPAddr, nic_name=clientNICName, count=packetCount, sudo=True)
        icmpResult = icmpResult.wait_result()
        return icmpResult
    elif protocol == "udp":
        log.info(f"Generate UDP traffic from {clientNICIPAddr} to {serverNICIPAddr}, total packet count:{packetCount}")
        # serverResult = serverNode.tools[Iperf3].run_as_server_async(port=port, one_connection_only=True, bind=serverNICIPAddr, daemon=False)
        # clientResult = clientNode.tools[Iperf3].run_as_client(server_ip=serverNICIPAddr,port=port,client_ip=clientNICIPAddr,bitrate=bitRate, buffer_length=packetLength, udp_mode=True)
        asyncio.run(setupServer(serverNode, port, serverNICIPAddr, log))
        setupClient(clientNode, port, serverNICIPAddr, clientNICIPAddr, str(packetLength), "", False, str(bitRate), log)


async def setupServer(node, serverPort, serverNICIPAddr, log):
    servercmd = f"iperf3 -s -p {serverPort} -B {serverNICIPAddr} --one-off -D"
    log.info(f"Server Command : {servercmd}")
    result = node.execute(servercmd)
    log.info(f"Result for Running the Server in IPAddress {serverNICIPAddr} : {result.stdout}")


def setupClient(node, destionationPort, destinationIPAddr, clientNICIPAddr, bufferLength, numberOfBytes, udpMode, bitRate, log):
    if udpMode:
        clientcmd = f"iperf3 -c {destinationIPAddr} -p {destionationPort} -B {clientNICIPAddr} -u -l {bufferLength} -b {bitRate}"
    else:
        clientcmd = f"iperf3 -c {destinationIPAddr} -p {destionationPort} -B {clientNICIPAddr} -l {bufferLength} -n {numberOfBytes}"
    log.info(f"Client Command : {clientcmd}")
    result = node.execute(clientcmd)
    log.info(f"Result for Running the Client in IPAddress {clientNICIPAddr} : {result.stdout}")


def testTCPUDPTraffic(firewallNode,clientNICName, clientNode,serverNode,serverNICIPAddr,clientNICIPAddr,port,protocol,log):
    log.info(f"Sending TCP Traffic from {clientNICIPAddr} to {serverNICIPAddr} on port {port}")
    generateTraffic(clientNode, serverNode, protocol, clientNICIPAddr, clientNICName, serverNICIPAddr, log)
    verifyConntrackEntry(firewallNode, clientNICIPAddr, serverNICIPAddr, protocol, "256", log)
    result = firewallNode.execute(f"iptables-save",sudo=True)
    log.info(f"Before Reloading Rules IPTable Result : {result.stdout}")
    log.info(f"Reloading Firewall Rules {udpRuleConfigName}")
    reloadRules(firewallNode, udpRuleConfigName, log)
    result = firewallNode.execute(f"iptables-save",sudo=True)
    log.info(f"After Reloading Rules IPTable Result: {result.stdout}")
    verifyConntrackEntry(firewallNode, clientNICIPAddr, serverNICIPAddr, protocol, "0", log)
    generateTraffic(clientNode, serverNode, protocol, clientNICIPAddr, clientNICName, serverNICIPAddr, log)
    verifyConntrackEntry(firewallNode, clientNICIPAddr, serverNICIPAddr, protocol, "256", log)


def testUDPTraffic(firewallNode,clientNode,serverNode,serverNICIPAddr,clientNICIPAddr,port,log):

    log.info(f"Sending UDP Traffic from {clientNICIPAddr} to {serverNICIPAddr} on port {port}")
    serverNode.tools[Iperf3].run_as_server_async(port=port,one_connection_only=True,bind=serverNICIPAddr,daemon=False)
    clientNode.tools[Iperf3].run_as_client_async(server_ip=serverNICIPAddr,port=5201,run_time_seconds=180,client_ip=clientNICIPAddr, udp_mode=True)
    conntrackdump = firewallNode.execute("conntrack -L", sudo=True)
    iptablesdump = firewallNode.execute("iptables-save", sudo=True)
    log.info(f"Conntrack Dump: {conntrackdump.stdout}")
    log.info(f"Iptables Dump: {iptablesdump.stdout}")     
    log.info(f"Reloading Firewall Rules {udpRuleConfigName}")
    reloadRules(firewallNode, udpRuleConfigName, log)
    conntrackdump = firewallNode.execute('conntrack -L | grep', sudo=True)
    iptablesdump = firewallNode.execute("iptables-save", sudo=True)
    log.info(f"Conntrack Dump: {conntrackdump.stdout}")
    log.info(f"Iptables Dump: {iptablesdump.stdout}")


def parse_conntrack_dump(conntrackDump, clientIPAddr, destinationIPAddr):
    lines = conntrackDump.strip().split('\n')
    icmp_entries = []

    icmp_pattern = re.compile(
        r'icmp\s+\d+\s+\d+\s+src=(?P<src1>\S+)\s+dst=(?P<dst1>\S+)\s+type=(?P<type1>\d+)\s+code=(?P<code1>\d+)\s+id=(?P<id1>\d+)\s+'
        r'src=(?P<src2>\S+)\s+dst=(?P<dst2>\S+)\s+type=(?P<type2>\d+)\s+code=(?P<code2>\d+)\s+id=(?P<id2>\d+)'
    )

    for line in lines:
        match = icmp_pattern.search(line)
        if match:
            request_src = match.group('src1')
            request_dst = match.group('dst1')
            reply_src = match.group('src2')
            reply_dst = match.group('dst2')

            if request_src == clientIPAddr and request_dst == destinationIPAddr and reply_src == destinationIPAddr and reply_dst == clientIPAddr:
                entry = {
                    'request': {
                        'src': request_src,
                        'dst': request_dst,
                        'type': int(match.group('type1')),
                        'code': int(match.group('code1')),
                        'id': int(match.group('id1'))
                    },
                    'reply': {
                        'src': reply_src,
                        'dst': reply_dst,
                        'type': int(match.group('type2')),
                        'code': int(match.group('code2')),
                        'id': int(match.group('id2'))
                    }
                }
                icmp_entries.append(entry)

    return icmp_entries

# ipv4 network longest prefix match helper. Assumes 24bit mask
def ipv4_to_lpm(addr: str) -> str:
    return ".".join(addr.split(".")[:3]) + ".0/24"    

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
    availableNICs, availableNICsIPaddr = getNodesNICandIPaddr(clientNode, log)
    for i in range(niccount):
        nic = availableNICsIPaddr[i]
        client_subnet = ".".join(nic.split(".")[:3])
        if client_subnet != fw_subnet:
            clientNICName = availableNICs[i]
            clientNICIPAddr = availableNICsIPaddr[i]
            log.info(f"Client Node: {clientNode.name}, NIC: {clientNICName}, IP Address: {clientNICIPAddr}")
            break

    # Node 2: Server (Choose NIC which is in same subnet as Client)
    serverNode = cast(RemoteNode, environment.nodes[2])
    availableNICs, availableNICsIPaddr = getNodesNICandIPaddr(serverNode, log)
    for i in range(niccount):
        nic = availableNICsIPaddr[i]
        server_subnet = ".".join(nic.split(".")[:3])
        if server_subnet == client_subnet:
            serverNICName = availableNICs[i]
            serverNICIPAddr = availableNICsIPaddr[i]
            log.info(f"Server Node: {serverNode.name}, NIC: {serverNICName}, IP Address: {serverNICIPAddr}")
            break

    return firewallNode, clientNode, serverNode, clientNICName, clientNICIPAddr, serverNICName, serverNICIPAddr, firewallNICName, firewallNICIPAddr

def getNodesNICandIPaddr(node, log):

    log.info(f"Fetch all the available NICs for node: {node.name}")

    availableNICs = []
    availableNICsIPaddr = []

    for i in range(niccount):
        availableNICs.append(node.nics.get_nic_by_index(i).name)
        availableNICsIPaddr.append(node.nics.get_nic_by_index(i).ip_addr)
        log.info(f"NIC {i} Name: {availableNICs[i]}, IP Address: {availableNICsIPaddr[i]}")

    return availableNICs, availableNICsIPaddr

def delFirewallNICRoutes(firewallNICIPAddr,firewallNode, log):

    log.info("Deleting Azure Firewall's NIC routes")

    #GET the NICs and their IP addresses
    firewallNICs, firewallNICsIPaddr = getNodesNICandIPaddr(firewallNode, log)
    log.info(f"Firewall NICs: {firewallNICs}, Firewall NICs IP addresses: {firewallNICsIPaddr}")

    deletenicroutes = []
    #Delete the routes for NIC 1 and NIC 2
    for ipaddr in firewallNICsIPaddr:
        if ipaddr not in firewallNICIPAddr:
            deletenicroutes.append(ipaddr)
    
    deleteiproute(deletenicroutes, firewallNode, log)

    firewallRoutes = firewallNode.execute("ip route show", sudo=True)
    log.info(f"Routes after deletion: {firewallRoutes}")

def deleteiproute(ipaddresses, node, log):

    for ipaddr in ipaddresses:
        log.info(f"Deleting all the routes for IP address: {ipaddr} on node: {node.name}")
        result = node.execute(f"ip route show", sudo=True)
        log.info(f"Current available routes in Firewall VM: {result.stdout.splitlines()}")
        for route in result.stdout.splitlines():
            if ipaddr in route:
                log.info(f"Deleting route: {route}")
                node.execute(f"ip route del {route}", sudo=True)
        
#Enable Key Vault VM Extension on the Firewall VM to provision Geneva Certificates from Client Node
def enableKeyVaultVMExtension(clientNode, resourceGroupName, firewallVMName, settingsFileName, settingsFilePath, log):

    GsaTestStorageBlobReaderIdentity = "/subscriptions/e7eb2257-46e4-4826-94df-153853fea38f/resourcegroups/gsatestresourcegroup/providers/Microsoft.ManagedIdentity/userAssignedIdentities/gsateststorage-blobreader"

    clientNode.execute("sudo tdnf install -y azure-cli", sudo=True)
    result = clientNode.execute(f"az login --identity --resource-id {GsaTestStorageBlobReaderIdentity}")
    log.info('Successfully logged into lisa storage', result.stdout)

    #Download the settings.json file from blob storage
    log.info(f"Downloading settings.json {settingsFileName} file from blob storage to {settingsFilePath} on node: {clientNode.name}")
    command = f"az storage blob download --auth-mode login --account-name {lisaStorageAccountName} -c {lisaContainerName} -n {settingsFileName} -f {settingsFilePath}"
    result = clientNode.execute(command)
    log.info(f"Result for downloading settings.json {settingsFileName} file from blob storage: {result.stdout}")

    log.info(f"Enabling Key Vault VM Extension on {firewallVMName} which is present in {resourceGroupName} resource group from node : {clientNode.name}")
    command = f'az vm extension set -n "KeyVaultForLinux" --publisher Microsoft.Azure.KeyVault --resource-group {resourceGroupName} --vm-name {firewallVMName} --version 3.0 --enable-auto-upgrade --settings {settingsFilePath}'
    result = clientNode.execute(command)
    log.info("Successfully enabled Key Vault VM Extension", result)

def reloadRules(firewallNode, ruleConfigName, log):
    cseparams = {
            "RULE_CONFIG_URL": f"https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/{ruleConfigName}",
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
            "TENANT_IDENTITY_RESOURCE_ID": "/subscriptions/11764614-ffac-4e4d-8506-bdf64388ce6c/resourcegroups/Bala-LisaTestResourcesRG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/lisatestaccessidentity",
            "REGIONAL_KEYVAULT_URL": "https://fwcreationkeyvault.vault.azure.net/",
            "REGIONAL_IDENTITY_RESOURCE_ID": "/subscriptions/11764614-ffac-4e4d-8506-bdf64388ce6c/resourcegroups/Bala-LisaTestResourcesRG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/lisatestaccessidentity",
            "NOSNAT_IPPREFIXES_CONFIG_SAS_URL": None,
            "NOSNAT_IS_AUTO_LEARN_ENABLED": None
    }
    json_str = json.dumps(cseparams)
    # escaped_json = json_str.replace('"', '\\"')
    command = f"/opt/azfw/bin/cse_runner.sh '{json_str}'"
    result = firewallNode.execute(f"bash -x {command}", sudo=True)
    log.info("Reloaded Rules", result.stdout)

def firewallInit(firewallNode, log):
    GsaTestStorageBlobReaderIdentity = "/subscriptions/e7eb2257-46e4-4826-94df-153853fea38f/resourcegroups/gsatestresourcegroup/providers/Microsoft.ManagedIdentity/userAssignedIdentities/gsateststorage-blobreader"

    firewallNode.execute("sudo tdnf install -y azure-cli", sudo=True)

    result = firewallNode.execute(f"az login --identity --resource-id {GsaTestStorageBlobReaderIdentity}")
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
    # firewallNode.execute("mv /tmp/mdsd.service /etc/systemd/system/mdsd.service", sudo=True)
    # firewallNode.execute("mv /tmp/mock_statsd.service /etc/systemd/system/mock_statsd.service", sudo=True)
    # firewallNode.execute("mv /tmp/mock_statsd.py /opt/mock_statsd.py", sudo=True)
    # firewallNode.execute("mv /tmp/mock_mdsd /opt/mock_mdsd", sudo=True)
    firewallNode.execute("useradd -M -e 2100-01-01 azfwuser", sudo=True)
    
    # Reload daemon 
    result = firewallNode.execute("sudo systemctl daemon-reload", sudo=True)
    log.info("Daemon reloaded successfully", result)
    #Restart mdsd and mdsd.statsd service
    # result = firewallNode.execute("sudo systemctl restart mock_statsd.service", sudo=True)
    # result = firewallNode.execute("sudo systemctl restart mdsd.service", sudo=True)
    
    # Continue with your blob download and other operations
    result = firewallNode.execute("az storage blob download --auth-mode login --account-name gsateststorage -c app -n app/app-15817278/bootstrap.tar -f /tmp/bootstrap.tar") #Done
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

    # result = firewallNode.execute("mv /tmp/bootstrap_geneva.sh /tmp/bootstrap/drop/vmss/bootstrap_geneva.sh", sudo=True) #Done

    result = firewallNode.execute("sed -i '461d' /tmp/bootstrap/drop/vmss/azfw_common.sh", sudo=True) #Done
    result = firewallNode.execute("sed -i '79d' /tmp/bootstrap/drop/vmss/bootstrap.sh", sudo=True)    #Done

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
            "TENANT_IDENTITY_RESOURCE_ID": "/subscriptions/11764614-ffac-4e4d-8506-bdf64388ce6c/resourcegroups/Bala-LisaTestResourcesRG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/lisatestaccessidentity",
            "REGIONAL_KEYVAULT_URL": "https://fwcreationkeyvault.vault.azure.net/",
            "REGIONAL_IDENTITY_RESOURCE_ID": "/subscriptions/11764614-ffac-4e4d-8506-bdf64388ce6c/resourcegroups/Bala-LisaTestResourcesRG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/lisatestaccessidentity",
            "NOSNAT_IPPREFIXES_CONFIG_SAS_URL": None,
            "NOSNAT_IS_AUTO_LEARN_ENABLED": None
        }

    json_str = json.dumps(json_value)
    # escaped_json = json_str.replace('"', '\\"')
    command = f"/tmp/bootstrap/drop/vmss/bootstrap.sh '{json_str}'"
    result = firewallNode.execute(f"bash -x {command}", sudo=True)
    log.info("Successfully executed bootstrap.sh", result)