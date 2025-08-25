from lisa.features import NetworkInterface
from lisa.sut_orchestrator.azure.common import (
    get_node_context,
)
import json 

async def enableNICIPForwarding(node, nodeNICIPAddr, log):
    log.info(f"Enable IP Forwarding for IP Addr : {nodeNICIPAddr}")
    node.features[NetworkInterface].switch_ip_forwarding(enable=True, private_ip_addr=nodeNICIPAddr)



# async def verifyConntrackEntry(node, sourceNICIPAddr, destinationNICIPAddr, protocol, mask, log):
#     log.info(f"Verifying conntrack entry for Protocol {protocol} from {sourceNICIPAddr} to {destinationNICIPAddr}")
#     result = node.execute(f"bash -c \"conntrack -L | grep '{sourceNICIPAddr}' | grep '{destinationNICIPAddr}' | grep '{protocol}' | grep '{mask}'\"", sudo=True)
#     if result.stdout.splitlines().length >1:
#         return True
#     else:
#         return False

def enableKeyVaultVMExtension(node, resourceGroupName, firewallVMName, settingsFileName, settingsFilePath, storageAccountName, storageContainerName, log):


    log.info(f"Enabling Key Vault VM Extension on {firewallVMName} which is present in {resourceGroupName} resource group from node : {node.name}")
    command = f'az vm extension set -n "KeyVaultForLinux" --publisher Microsoft.Azure.KeyVault --resource-group {resourceGroupName} --vm-name {firewallVMName} --version 3.0 --enable-auto-upgrade --settings {settingsFilePath}'
    result = node.execute(command)
    log.debug(f"Result for executing {command} {result.stdout}")
    if '"certificateStoreLocation": "/var/lib/waagent/"' in result.stdout:
        log.info(f"Enabling Key Vault VM Extension on {firewallVMName} through Node {node.name} is successful")
        return 1
    else:
        return 0

def downloadFilesFromBlob(node, fileName, filePath, storageAccountName, storageContainerName, log):
    log.debug(f"Downloading {fileName} and saving to {filePath}")
    command = f"az storage blob download --auth-mode login --account-name {storageAccountName} -c {storageContainerName} -n {fileName} -f {filePath}"
    result = node.execute(command)
    log.debug(f"Result for downloading {fileName} file from blob storage: {result.stdout}")

def loginAzureCLI(node, managedIdentity, log):

    node.execute("sudo tdnf install -y azure-cli", sudo=True)
    result = node.execute(f"az login --identity --resource-id {managedIdentity}")

def installAzureCLI(node, log):
    log.info("Installing Azure CLI")
    result = node.execute("sudo tdnf install -y azure-cli", sudo=True)
    log.debug(f"Result for installing azure-cli: {result.stdout}")

def getResourceGroupName(node, log):
    nodeContext = get_node_context(node)
    return nodeContext.resource_group_name

def getNodesNICandIPaddr(node, niccount, log):

    log.info(f"Fetch all the available NICs for node: {node.name}")

    availableNICs = []
    availableNICsIPaddr = []

    for i in range(niccount):
        availableNICs.append(node.nics.get_nic_by_index(i).name)
        availableNICsIPaddr.append(node.nics.get_nic_by_index(i).ip_addr)
        log.info(f"NIC {i} Name: {availableNICs[i]}, IP Address: {availableNICsIPaddr[i]}")

    return availableNICs, availableNICsIPaddr

def deleteIPRoute(node, ipaddresses, log):
    log.info("Deleting Azure Firewall's NIC routes")

    for ipaddr in ipaddresses:
        log.info(f"Deleting all the routes for IP address: {ipaddr} on node: {node.name}")
        result = node.execute(f"ip route show", sudo=True)
        log.info(f"Current available routes in Firewall VM: {result.stdout.splitlines()}")
        for route in result.stdout.splitlines():
            if ipaddr in route:
                log.info(f"Deleting route: {route}")
                node.execute(f"ip route del {route}", sudo=True)

def reloadRules(node, ruleConfigName, managedIdentity, log):
    cseParams = {
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
        "TENANT_IDENTITY_RESOURCE_ID": f"{managedIdentity}",
        "REGIONAL_KEYVAULT_URL": "https://fwcreationkeyvault.vault.azure.net/",
        "REGIONAL_IDENTITY_RESOURCE_ID": f"{managedIdentity}",
        "NOSNAT_IPPREFIXES_CONFIG_SAS_URL": None,
        "NOSNAT_IS_AUTO_LEARN_ENABLED": None
    }
    json_data = json.dumps(cseParams)
    command = f"/opt/azfw/bin/cse_runner.sh '{json_data}'"
    log.info(f"Reloading rules with command: {command}")
    result = node.execute(command, sudo=True)
    log.debug(f"CSE Runner Execute Result : {result.stdout}")
    if "CSE runner finished" in result.stdout:
        return 1
    else: 
        return 0


async def verifyIPTables(iptablesDump, arraytoMatch, log):
    iptables = iptablesDump.splitlines()
    for ipTableEntry in arraytoMatch:
        if ipTableEntry not in iptables:
            log.info(f"Not matched  : {ipTableEntry}")
            return False
    return True

def verifyConntrackEntry(node, clientNICIPAddr, serverNICIPAddr, protocol, mask, log):
    log.info(f"Verifying conntrack entry for Protocol {protocol} from {clientNICIPAddr} to {serverNICIPAddr} in node {node.name}")
    result = node.execute(f"bash -c \"conntrack -L | grep '{clientNICIPAddr}' | grep '{serverNICIPAddr}' | grep '{protocol}' | grep '{mask}'\"", sudo=True)
    if len(result.stdout.splitlines()) > 1:
        log.info("Conntrack Entry Found")
        return 1
    else:
        return 0
    
def ipv4_to_lpm(addr: str) -> str:
    return ".".join(addr.split(".")[:3]) + ".0/24" 