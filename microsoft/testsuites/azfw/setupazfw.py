# from typing import cast
# import json
# # from lisa.sut_orchestrator.azure.common import add_user_assign_identity
# from lisa import (
#     Environment,
#     Logger,
#     RemoteNode,
#     TestSuite,
#     TestSuiteMetadata,
#     TestCaseMetadata,
#     simple_requirement,
# )
# from lisa.features import NetworkInterface
# from lisa.tools import Ls, Mkdir, Sysctl
# import time

# #Constants
# gsaManagedIdentity = "/subscriptions/e7eb2257-46e4-4826-94df-153853fea38f/resourcegroups/gsatestresourcegroup/providers/Microsoft.ManagedIdentity/userAssignedIdentities/gsateststorage-blobreader"
# lisaStorageAccountName = "lisatestresourcestorage"
# lisaContainerName = "fwcreateconfigfiles"
# firewallAppVersion = "app-15432201"
# bootstrapFileName = f"app/{firewallAppVersion}/bootstrap.tar"
# gsaContainerName = "app"
# gsaStorageAccountName = "gsateststorage"
# cseparams = {
#         "RULE_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/ruleConfig.json",
#         "RULE_CONFIG_NAME": "a36eb125-41ee-4e34-8158-c14c0c75ee4a",
#         "SETTINGS_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/mdsMetadata.txt",
#         "GENEVATHUMBPRINT": "3BD30EA445312E57C4C2AD1152524BE5D35E3937",
#         "FQDN_TAGS_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/defaultfqdntags.json",
#         "SERVICE_TAGS_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/servicetags.json",
#         "WEB_CATEGORIES_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/defaultwebcategories.json",
#         "IDPS_RULES_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/rules.tar.gz",
#         "IDPS_RULES_OVERRIDES_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/instrusionsystemoverrides.json",
#         "INTERFLOW_KEY": "c70e2937d7984d41bab046ad131fcbe0",
#         "WEB_CATEGORIZATION_VENDOR_LICENSE_KEY": "7gk92m7cNiKmFtfkjwPua64zEVk2ct7z",
#         "AAD_TENANT_ID": "33e01921-4d64-4f8c-a055-5bdaffd5e33d",
#         "AAD_CLIENT_ID": "074a0fa4-34df-493f-985b-d3dedb49748b",
#         "AAD_SECRET": "LZJeyEbkqM0Z+6B]l65ucj=WK-P@7d]*",
#         "NUMBER_PUBLIC_IPS": 1,
#         "NUMBER_PORTS_PER_PUBLIC_IP": 2496,
#         "DATA_SUBNET_PREFIX": "10.0.0.0/24",
#         "DATA_SUBNET_PREFIX_IPV6": "",
#         "MGMT_SUBNET_PREFIX": "",
#         "ROUTE_SERVICE_CONFIG_URL": None,
#         "TENANT_KEYVAULT_URL": "https://fwcreationkeyvault.vault.azure.net/",
#         "TENANT_IDENTITY_RESOURCE_ID": "/subscriptions/11764614-ffac-4e4d-8506-bdf64388ce6c/resourcegroups/Bala-LisaTestResourcesRG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/lisatestaccessidentity",
#         "REGIONAL_KEYVAULT_URL": "https://fwcreationkeyvault.vault.azure.net/",
#         "REGIONAL_IDENTITY_RESOURCE_ID": "/subscriptions/11764614-ffac-4e4d-8506-bdf64388ce6c/resourcegroups/Bala-LisaTestResourcesRG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/lisatestaccessidentity",
#         "NOSNAT_IPPREFIXES_CONFIG_SAS_URL": None,
#         "NOSNAT_IS_AUTO_LEARN_ENABLED": None
#     }


# @TestSuiteMetadata(
#     area="azure-firewall",
#     category="functional",
#     description="""
#     This test suite sets up Azure Firewall for testing purposes.
#     It ensures that the firewall is configured correctly and ready for use.
#     """,
#     requirement=simple_requirement(min_count=3, min_nic_count=3),

# )
# class azureFirewallTests(TestSuite):  
#     @TestCaseMetadata(
#         description="""
#         This test case sets up Azure Firewall with the specified configuration.
#         It verifies that the firewall is created and configured correctly.
#         """,
#         priority=1,
#     )
#     def setup_azureFirewall(self, environment: Environment, log: Logger) -> None:
#         GsaTestStorageBlobReaderIdentity = "/subscriptions/e7eb2257-46e4-4826-94df-153853fea38f/resourcegroups/gsatestresourcegroup/providers/Microsoft.ManagedIdentity/userAssignedIdentities/gsateststorage-blobreader"
#         log.info("Setting up App Version....")
#         firewallNode = cast(RemoteNode, environment.nodes[0])

#         firewallNode.execute("sudo tdnf install -y azure-cli", sudo=True)

#         try:
#             result = firewallNode.execute(f"az login --identity --resource-id {GsaTestStorageBlobReaderIdentity}")
#             log.info('Successfully logged into lisa storage', result)
            
#             #download necessary files from blob storage
#             files = ["mdsd.service", "mock_statsd.service", "mock_statsd.py", "mock_mdsd", "install_runtime_deps.sh", "importdatafromjson.py", "cseparams.json", "bootstrap_geneva.sh"]
#             for file in files:
#                 firewallNode.execute(f"az storage blob download --auth-mode login --account-name lisatestresourcestorage  -c fwcreateconfigfiles -n {file} -f /tmp/{file}")

#             result = firewallNode.execute("chmod 666 /tmp/mdsd.service /tmp/mock_statsd.service /tmp/mock_statsd.py /tmp/mock_mdsd /tmp/install_runtime_deps.sh /tmp/importdatafromjson.py bootstrap_geneva.sh", sudo=True)
#             result = firewallNode.execute("chmod -R 777 /tmp/mdsd.service /tmp/mock_statsd.service /tmp/mock_statsd.py /tmp/mock_mdsd /tmp/install_runtime_deps.sh /tmp/importdatafromjson.py bootstrap_geneva.sh", sudo=True)

#             #Generate mdsMetadata.txt file
#             result = firewallNode.execute("python3 /tmp/importdatafromjson.py", sudo=True)
#             log.info("Successfully generated mdsMetadata.txt", result)
#             #Upload the mdsMetadata.txt file to blob storage
#             result = firewallNode.execute("az storage blob upload --auth-mode login --account-name lisatestresourcestorage  -c fwcreateconfigfiles -n mdsMetadata.txt -f /tmp/mdsMetadata.txt", sudo=True) # Done 
#             log.info("Successfully uploaded mdsMetadata.txt to blob storage", result) # Done

#             result = firewallNode.execute("bash -x /tmp/install_runtime_deps.sh", sudo=True)
#             log.info("Successfully executed install_runtime_deps.sh", result.stdout)
#             firewallNode.execute("mv /tmp/mdsd.service /etc/systemd/system/mdsd.service", sudo=True)
#             firewallNode.execute("mv /tmp/mock_statsd.service /etc/systemd/system/mock_statsd.service", sudo=True)
#             firewallNode.execute("mv /tmp/mock_statsd.py /opt/mock_statsd.py", sudo=True)
#             firewallNode.execute("mv /tmp/mock_mdsd /opt/mock_mdsd", sudo=True)
#             firewallNode.execute("useradd -M -e 2100-01-01 azfwuser", sudo=True)
            
#             # Reload daemon 
#             result = firewallNode.execute("sudo systemctl daemon-reload", sudo=True)
#             log.info("Daemon reloaded successfully", result)
#             #Restart mdsd and mdsd.statsd service
#             result = firewallNode.execute("sudo systemctl restart mock_statsd.service", sudo=True)
#             result = firewallNode.execute("sudo systemctl restart mdsd.service", sudo=True)
            
#             # Continue with your blob download and other operations
#             result = firewallNode.execute("az storage blob download --auth-mode login --account-name gsateststorage -c app -n app/app-15817278/bootstrap.tar -f /tmp/bootstrap.tar") #Done
#             log.info("Successfully downloaded bootstrap.tar", result) #Done

#             result = firewallNode.execute("sudo chmod 666 /tmp/bootstrap.tar", sudo=True) #Done
#             log.info("Changed permissions for bootstrap.tar", result) #Done

#             result = firewallNode.execute("sudo chmod -R 777 /tmp/bootstrap.tar", sudo=True) #Done
#             log.info("Changed permissions for bootstrap.tar", result) #Done


#             result = firewallNode.execute("mkdir /tmp/bootstrap/") #Done
#             log.info("Created Directory /tmp/bootstrap/", result)

#             result = firewallNode.execute("python -m ensurepip", sudo=True) #done
#             log.info("Successfully installed psutil", result)
#             result = firewallNode.execute('export PATH="$PATH:/home/lisatest/.local/bin"') #done
#             log.info("Added /home/lisatest/.local/bin to PATH", result)
#             result = firewallNode.execute(" python -m pip install psutil", sudo=True) #Done
#             log.info("Successfully installed psutil", result)

#             result = firewallNode.execute("tar -xvf /tmp/bootstrap.tar -C /tmp/bootstrap/", sudo=True) #Done
#             log.info("Successfully extracted bootstrap.tar")

#             result = firewallNode.execute("mv /tmp/bootstrap_geneva.sh /tmp/bootstrap/drop/vmss/bootstrap_geneva.sh", sudo=True) #Done

#             result = firewallNode.execute("sed -i '461d' /tmp/bootstrap/drop/vmss/azfw_common.sh", sudo=True) #Done
#             result = firewallNode.execute("sed -i '79d' /tmp/bootstrap/drop/vmss/bootstrap.sh", sudo=True)    #Done

#             json_value = {
#                     "RULE_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/ruleConfig.json",
#                     "RULE_CONFIG_NAME": "a36eb125-41ee-4e34-8158-c14c0c75ee4a",
#                     "SETTINGS_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/mdsMetadata.txt",
#                     "GENEVATHUMBPRINT": "3BD30EA445312E57C4C2AD1152524BE5D35E3937",
#                     "FQDN_TAGS_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/defaultfqdntags.json",
#                     "SERVICE_TAGS_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/servicetags.json",
#                     "WEB_CATEGORIES_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/defaultwebcategories.json",
#                     "IDPS_RULES_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/rules.tar.gz",
#                     "IDPS_RULES_OVERRIDES_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/instrusionsystemoverrides.json",
#                     "INTERFLOW_KEY": "c70e2937d7984d41bab046ad131fcbe0",
#                     "WEB_CATEGORIZATION_VENDOR_LICENSE_KEY": "7gk92m7cNiKmFtfkjwPua64zEVk2ct7z",
#                     "AAD_TENANT_ID": "33e01921-4d64-4f8c-a055-5bdaffd5e33d",
#                     "AAD_CLIENT_ID": "074a0fa4-34df-493f-985b-d3dedb49748b",
#                     "AAD_SECRET": "LZJeyEbkqM0Z+6B]l65ucj=WK-P@7d]*",
#                     "NUMBER_PUBLIC_IPS": 1,
#                     "NUMBER_PORTS_PER_PUBLIC_IP": 2496,
#                     "DATA_SUBNET_PREFIX": "10.0.0.0/24",
#                     "DATA_SUBNET_PREFIX_IPV6": "",
#                     "MGMT_SUBNET_PREFIX": "",
#                     "ROUTE_SERVICE_CONFIG_URL": None,
#                     "TENANT_KEYVAULT_URL": "https://fwcreationkeyvault.vault.azure.net/",
#                     "TENANT_IDENTITY_RESOURCE_ID": "/subscriptions/11764614-ffac-4e4d-8506-bdf64388ce6c/resourcegroups/Bala-LisaTestResourcesRG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/lisatestaccessidentity",
#                     "REGIONAL_KEYVAULT_URL": "https://fwcreationkeyvault.vault.azure.net/",
#                     "REGIONAL_IDENTITY_RESOURCE_ID": "/subscriptions/11764614-ffac-4e4d-8506-bdf64388ce6c/resourcegroups/Bala-LisaTestResourcesRG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/lisatestaccessidentity",
#                     "NOSNAT_IPPREFIXES_CONFIG_SAS_URL": None,
#                     "NOSNAT_IS_AUTO_LEARN_ENABLED": None
#                 }

#             json_str = json.dumps(json_value)
#             # escaped_json = json_str.replace('"', '\\"')
#             command = f"/tmp/bootstrap/drop/vmss/bootstrap.sh '{json_str}'"
#             result = firewallNode.execute(f"bash -x {command}", sudo=True)
#             log.info("Successfully executed bootstrap.sh", result)

#             # clientNode = cast(RemoteNode, environment.nodes[1])
#             # log.info("Setting up client with necessary packages...")
            
#             # result = clientNode.execute("curl https://www.google.com", sudo=True)
#             # log.info("Result for pinging google.com before adding firewall in route:", result.stdout)

#             # #Add firweall in route
#             # log.info("Adding Azure Firewall in route...")
#             # result = clientNode.execute("ip route del default", sudo=True)
#             # log.info("Result for deleting default route:", result.stdout)

#             # result = clientNode.execute("ip route add default via 10.0.0.4", sudo=True)
#             # log.info("Result for adding Azure Firewall in route:", result.stdout)

#             # result = clientNode.execute("curl https://www.google.com", sudo=True)
#             # log.info("Result for pinging google.com after adding firewall in route:", result.stdout)
#             verifylogrotate(firewallNode,log)
#         except Exception as e:
#             log.error(f"Failed to setup Azure Firewall: {str(e)}")
#             raise        
        
#         createRouteTable(environment, log)
    




    
#     @TestCaseMetadata(
#             description= """
#                 This test will verify if Application rules are working
#             """,
#             priority=1,
#     )
#     def testApplicationRules(self, environment: Environment, log: Logger) -> None:
#         firewallNode = cast(RemoteNode, environment.nodes[0])
#         clientNode = cast(RemoteNode, environment.nodes[1])
#         firewallInit(firewallNode,log)
#         log.info("Done Setting up Azure Firewall in VM")
#         log.info("Creating Route Tables")
#         createRouteTable(environment,log)

#         result = clientNode.execute("curl --retry 5 https://www.google.com")
#         if("Google Search" in result.stdout):
#             log.info("Able to successfully ping google.com")
#         else:
#             log.error("Not able to ping google.com")

#         result = clientNode.execute("curl --retry 5 https://www.microsoft.com")
#         if ("microsoft" in result.stdout):
#             log.error("Able to successfully ping microsoft.com, firewall is not blocking the traffic")
#         else: 
#             log.info("Firewall is able to successfully block traffic to microsoft.com")


#     @TestCaseMetadata(
#         description="""
#             This test case will verify whether the logrotate is working as expected or not
#         """,
#         priority=1,
#     )
#     def verifylogrotate(self, environment: Environment, log: Logger) -> None:
#         firewallNode = cast(RemoteNode, environment.nodes[0])
#         firewallInit(firewallNode,log)
#         log.info("Done setting up Firewall")
#         log.info("Moving to Test: Verify if logrotation is successfull or not")
#         ls = firewallNode.tools[Ls]
#         retrycount = 10
#         while not (ls.path_exists("/var/log/syslog.1", sudo=True) or retrycount == 0):
#               time.sleep(60)
#               retrycount-=1

#         if(retrycount == 0):
#             log.error(f"Logrotate didn't kicked in.")
#         log.info("LogRotate kicked in and created new files")
#         time.sleep(60)
        
#         result = firewallNode.execute("du -sh /var/log/azfw_test.log", sudo=True)
#         if("0" not in result):
#             log.info("rsyslog is using new files for logging: ", result.stdout)
#         else:
#             log.error("rsyslog is not using new files for loggis:", result.stdout)

#     @TestCaseMetadata(
#         """
#             This test will run ESP traffic to verify whether the connmark is getting removed after the rules has been updated
#         """
#     )
#     def verifyConnMarkReset(self, environment: Environment, log: Logger) -> None:
#         # createRouteTable(environment,log)
#         firewallNode = cast(RemoteNode, environment.nodes[0])
#         clientNode = cast(RemoteNode, environment.nodes[1])
#         firewallInit(firewallNode,log)

#         #Download Azure-CLI and tcpdump
#         log.info("Install tcpdump and setup Azure-CLI")
#         setupAzureCLI(clientNode,log)
#         clientNode.execute("tdnf -y install tcpdump", sudo=True)


#         log.info("Download generateesp python script from blob to generate ESP traffic")
#         result = clientNode.execute("az storage blob download --auth-mode login --account-name lisatestresourcestorage -c fwcreateconfigfiles -n genereateesp.py -f /tmp/genereateesp.py")
#         log.info("Blob storage download", result._stdout)
#         result = clientNode.execute("az storage blob download --auth-mode login --account-name lisatestresourcestorage -c fwcreateconfigfiles -n startesp.py -f /tmp/startesp.py")
#         log.info("blob storage download result for start.py", result.stdout)


#         #Install pip and scapy
#         log.info("Verify whether pip is installed or not")
#         result = clientNode.execute("python3 -m ensurepip", sudo=True)
#         if("Successfully installed pip" not in result.stdout or "Requirement already satisfied: pip" not in result.stdout):
#             log.error("pip is not installed or unable to install")
#         log.info("pip is installed in client VM", result.stdout)


#         log.info("Installing scapy")
#         result = clientNode.execute("python3 -m pip install scapy", sudo=True)
#         if("Successfully installed scapy" not in result.stdout or "Requirement already satisfied: scapy" not in result.stdout):
#             log.error("Not able to install scapy")
#         log.info("Successfully install scapy", result.stdout)

#         #Run python script to generate traffic
#         result = clientNode.execute("python3 /tmp/startesp.py", sudo=True)
#         log.info(f"Result for generating ESP traffic:", result.stdout)

#         result = firewallNode.execute('conntrack -L', sudo=True)
#         log.info("Conntrack Output result:", result.stdout)

#         if ("unknown" not in result.stdout and "mark=256" not in result.stdout):
#             log.err("Unknown protocol type with mark 256 is not found in conntrack", result.stdout)
#         log.info("Found connection which has unknown protocol type with mark 256", result.stdout)

#         json_value = {
#             "RULE_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/ruleConfig.json",
#             "RULE_CONFIG_NAME": "a36eb125-41ee-4e34-8158-c14c0c75ee4a",
#             "SETTINGS_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/mdsMetadata.txt",
#             "GENEVATHUMBPRINT": "3BD30EA445312E57C4C2AD1152524BE5D35E3937",
#             "FQDN_TAGS_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/defaultfqdntags.json",
#             "SERVICE_TAGS_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/servicetags.json",
#             "WEB_CATEGORIES_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/defaultwebcategories.json",
#             "IDPS_RULES_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/rules.tar.gz",
#             "IDPS_RULES_OVERRIDES_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/instrusionsystemoverrides.json",
#             "INTERFLOW_KEY": "c70e2937d7984d41bab046ad131fcbe0",
#             "WEB_CATEGORIZATION_VENDOR_LICENSE_KEY": "7gk92m7cNiKmFtfkjwPua64zEVk2ct7z",
#             "AAD_TENANT_ID": "33e01921-4d64-4f8c-a055-5bdaffd5e33d",
#             "AAD_CLIENT_ID": "074a0fa4-34df-493f-985b-d3dedb49748b",
#             "AAD_SECRET": "LZJeyEbkqM0Z+6B]l65ucj=WK-P@7d]*",
#             "NUMBER_PUBLIC_IPS": 1,
#             "NUMBER_PORTS_PER_PUBLIC_IP": 2496,
#             "DATA_SUBNET_PREFIX": "10.0.0.0/24",
#             "DATA_SUBNET_PREFIX_IPV6": "",
#             "MGMT_SUBNET_PREFIX": "",
#             "ROUTE_SERVICE_CONFIG_URL": None,
#             "TENANT_KEYVAULT_URL": "https://fwcreationkeyvault.vault.azure.net/",
#             "TENANT_IDENTITY_RESOURCE_ID": "/subscriptions/11764614-ffac-4e4d-8506-bdf64388ce6c/resourcegroups/Bala-LisaTestResourcesRG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/lisatestaccessidentity",
#             "REGIONAL_KEYVAULT_URL": "https://fwcreationkeyvault.vault.azure.net/",
#             "REGIONAL_IDENTITY_RESOURCE_ID": "/subscriptions/11764614-ffac-4e4d-8506-bdf64388ce6c/resourcegroups/Bala-LisaTestResourcesRG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/lisatestaccessidentity",
#             "NOSNAT_IPPREFIXES_CONFIG_SAS_URL": None,
#             "NOSNAT_IS_AUTO_LEARN_ENABLED": None
#         }

#         json_str = json.dumps(json_value)
#         # escaped_json = json_str.replace('"', '\\"')
#         command = f"/opt/azfw/bin/cse_runner.sh '{json_str}'"
#         result = firewallNode.execute(f"bash -x {command}", sudo=True)
#         log.info("Successfully restarted cse_runner.sh", result)
#         #Restart cseparams.sh
#         conntrackcmd = f'conntrack -L | grep "unknown"'
#         result = firewallNode.execute(conntrackcmd, sudo=True)
#         if("unknown" not in result.stdout and "mark=0" not in result.stdout):
#             log.error("Connection mark reset is not successful", result.stdout)
#         log.info("Connection mark reset is successful", result.stdout) 

# # ipv4 network longest prefix match helper. Assumes 24bit mask
# def ipv4_to_lpm(addr: str) -> str:
#     return ".".join(addr.split(".")[:3]) + ".0/24"
   
# def createRouteTable(environment: Environment, log: Logger):
#     firewall, client = environment.nodes.list()

#     all_available_nics = []
#     all_available_ips = []
#     for nodes in environment.nodes.list():
#         log.info(f"Node : {nodes}")
#         respectivenics = [
#             nodes.nics.get_nic_by_index(x) for x in range(2)
#         ]
#         print(f"Node {nodes.name} has the following NICs: {[nic for nic in respectivenics]}")
#         for nic in respectivenics:
#             all_available_nics.append(nic)
#             ipaddr = nic.ip_addr+"/32"
#             all_available_ips.append(ipaddr)
#         print(f"Node {nodes.name} has the following IPs: {[nic.ip_addr for nic in respectivenics]}")


#     # log.info(f"Setting up Client Route - Nic Name:{client.nics[1]}, Nic ip_addr:{client.nics[1].ip_addr}")
#     client.features[NetworkInterface].create_route_table(
#         nic_name= all_available_nics[2].name,
#         route_name= "clientToFirewall",
#         subnet_mask= ipv4_to_lpm(all_available_nics[2].ip_addr),
#         em_first_hop= all_available_nics[2].ip_addr+"/32",
#         next_hop_type= "VirtualAppliance",
#         dest_hop= all_available_nics[0].ip_addr
#     )

#     firewall.features[NetworkInterface].create_route_table(
#         nic_name= all_available_nics[0].name,
#         route_name= "firewallRoute",
#         subnet_mask= ipv4_to_lpm(all_available_nics[0].ip_addr),
#         em_first_hop= "0.0.0.0/0",
#         next_hop_type= "VirtualAppliance",
#         dest_hop= all_available_nics[0].ip_addr
#     )

# # def firewallInit(firewallNode, log):
# #     GsaTestStorageBlobReaderIdentity = "/subscriptions/e7eb2257-46e4-4826-94df-153853fea38f/resourcegroups/gsatestresourcegroup/providers/Microsoft.ManagedIdentity/userAssignedIdentities/gsateststorage-blobreader"

# #     firewallNode.execute("sudo tdnf install -y azure-cli", sudo=True)

# #     result = firewallNode.execute(f"az login --identity --resource-id {GsaTestStorageBlobReaderIdentity}")
# #     log.info('Successfully logged into lisa storage', result)
    
# #     #download necessary files from blob storage
# #     files = ["mdsd.service", "mock_statsd.service", "mock_statsd.py", "mock_mdsd", "install_runtime_deps.sh", "importdatafromjson.py", "cseparams.json", "bootstrap_geneva.sh"]
# #     for file in files:
# #         firewallNode.execute(f"az storage blob download --auth-mode login --account-name lisatestresourcestorage  -c fwcreateconfigfiles -n {file} -f /tmp/{file}")

# #     result = firewallNode.execute("chmod 666 /tmp/mdsd.service /tmp/mock_statsd.service /tmp/mock_statsd.py /tmp/mock_mdsd /tmp/install_runtime_deps.sh /tmp/importdatafromjson.py bootstrap_geneva.sh", sudo=True)
# #     result = firewallNode.execute("chmod -R 777 /tmp/mdsd.service /tmp/mock_statsd.service /tmp/mock_statsd.py /tmp/mock_mdsd /tmp/install_runtime_deps.sh /tmp/importdatafromjson.py bootstrap_geneva.sh", sudo=True)

# #     #Generate mdsMetadata.txt file
# #     result = firewallNode.execute("python3 /tmp/importdatafromjson.py", sudo=True)
# #     log.info("Successfully generated mdsMetadata.txt", result)
# #     #Upload the mdsMetadata.txt file to blob storage
# #     result = firewallNode.execute("az storage blob upload --auth-mode login --account-name lisatestresourcestorage  -c fwcreateconfigfiles -n mdsMetadata.txt -f /tmp/mdsMetadata.txt", sudo=True) # Done 
# #     log.info("Successfully uploaded mdsMetadata.txt to blob storage", result) # Done

# #     result = firewallNode.execute("bash -x /tmp/install_runtime_deps.sh", sudo=True)
# #     log.info("Successfully executed install_runtime_deps.sh", result.stdout)
# #     firewallNode.execute("mv /tmp/mdsd.service /etc/systemd/system/mdsd.service", sudo=True)
# #     firewallNode.execute("mv /tmp/mock_statsd.service /etc/systemd/system/mock_statsd.service", sudo=True)
# #     firewallNode.execute("mv /tmp/mock_statsd.py /opt/mock_statsd.py", sudo=True)
# #     firewallNode.execute("mv /tmp/mock_mdsd /opt/mock_mdsd", sudo=True)
# #     firewallNode.execute("useradd -M -e 2100-01-01 azfwuser", sudo=True)
    
# #     # Reload daemon 
# #     result = firewallNode.execute("sudo systemctl daemon-reload", sudo=True)
# #     log.info("Daemon reloaded successfully", result)
# #     #Restart mdsd and mdsd.statsd service
# #     result = firewallNode.execute("sudo systemctl restart mock_statsd.service", sudo=True)
# #     result = firewallNode.execute("sudo systemctl restart mdsd.service", sudo=True)
    
# #     # Continue with your blob download and other operations
# #     result = firewallNode.execute("az storage blob download --auth-mode login --account-name gsateststorage -c app -n app/app-15817278/bootstrap.tar -f /tmp/bootstrap.tar") #Done
# #     log.info("Successfully downloaded bootstrap.tar", result) #Done

# #     result = firewallNode.execute("sudo chmod 666 /tmp/bootstrap.tar", sudo=True) #Done
# #     log.info("Changed permissions for bootstrap.tar", result) #Done

# #     result = firewallNode.execute("sudo chmod -R 777 /tmp/bootstrap.tar", sudo=True) #Done
# #     log.info("Changed permissions for bootstrap.tar", result) #Done


# #     result = firewallNode.execute("mkdir /tmp/bootstrap/") #Done
# #     log.info("Created Directory /tmp/bootstrap/", result)

# #     result = firewallNode.execute("python -m ensurepip", sudo=True) #done
# #     log.info("Successfully installed psutil", result)
# #     result = firewallNode.execute('export PATH="$PATH:/home/lisatest/.local/bin"') #done
# #     log.info("Added /home/lisatest/.local/bin to PATH", result)
# #     result = firewallNode.execute(" python -m pip install psutil", sudo=True) #Done
# #     log.info("Successfully installed psutil", result)

# #     result = firewallNode.execute("tar -xvf /tmp/bootstrap.tar -C /tmp/bootstrap/", sudo=True) #Done
# #     log.info("Successfully extracted bootstrap.tar")

# #     result = firewallNode.execute("mv /tmp/bootstrap_geneva.sh /tmp/bootstrap/drop/vmss/bootstrap_geneva.sh", sudo=True) #Done

# #     result = firewallNode.execute("sed -i '461d' /tmp/bootstrap/drop/vmss/azfw_common.sh", sudo=True) #Done
# #     result = firewallNode.execute("sed -i '79d' /tmp/bootstrap/drop/vmss/bootstrap.sh", sudo=True)    #Done

# #     json_value = {
# #             "RULE_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/ruleConfig.json",
# #             "RULE_CONFIG_NAME": "a36eb125-41ee-4e34-8158-c14c0c75ee4a",
# #             "SETTINGS_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/mdsMetadata.txt",
# #             "GENEVATHUMBPRINT": "3BD30EA445312E57C4C2AD1152524BE5D35E3937",
# #             "FQDN_TAGS_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/defaultfqdntags.json",
# #             "SERVICE_TAGS_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/servicetags.json",
# #             "WEB_CATEGORIES_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/defaultwebcategories.json",
# #             "IDPS_RULES_CONFIG_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/rules.tar.gz",
# #             "IDPS_RULES_OVERRIDES_URL": "https://lisatestresourcestorage.blob.core.windows.net/fwcreateconfigfiles/instrusionsystemoverrides.json",
# #             "INTERFLOW_KEY": "c70e2937d7984d41bab046ad131fcbe0",
# #             "WEB_CATEGORIZATION_VENDOR_LICENSE_KEY": "7gk92m7cNiKmFtfkjwPua64zEVk2ct7z",
# #             "AAD_TENANT_ID": "33e01921-4d64-4f8c-a055-5bdaffd5e33d",
# #             "AAD_CLIENT_ID": "074a0fa4-34df-493f-985b-d3dedb49748b",
# #             "AAD_SECRET": "LZJeyEbkqM0Z+6B]l65ucj=WK-P@7d]*",
# #             "NUMBER_PUBLIC_IPS": 1,
# #             "NUMBER_PORTS_PER_PUBLIC_IP": 2496,
# #             "DATA_SUBNET_PREFIX": "10.0.0.0/24",
# #             "DATA_SUBNET_PREFIX_IPV6": "",
# #             "MGMT_SUBNET_PREFIX": "",
# #             "ROUTE_SERVICE_CONFIG_URL": None,
# #             "TENANT_KEYVAULT_URL": "https://fwcreationkeyvault.vault.azure.net/",
# #             "TENANT_IDENTITY_RESOURCE_ID": "/subscriptions/11764614-ffac-4e4d-8506-bdf64388ce6c/resourcegroups/Bala-LisaTestResourcesRG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/lisatestaccessidentity",
# #             "REGIONAL_KEYVAULT_URL": "https://fwcreationkeyvault.vault.azure.net/",
# #             "REGIONAL_IDENTITY_RESOURCE_ID": "/subscriptions/11764614-ffac-4e4d-8506-bdf64388ce6c/resourcegroups/Bala-LisaTestResourcesRG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/lisatestaccessidentity",
# #             "NOSNAT_IPPREFIXES_CONFIG_SAS_URL": None,
# #             "NOSNAT_IS_AUTO_LEARN_ENABLED": None
# #         }

# #     json_str = json.dumps(json_value)
# #     # escaped_json = json_str.replace('"', '\\"')
# #     command = f"/tmp/bootstrap/drop/vmss/bootstrap.sh '{json_str}'"
# #     result = firewallNode.execute(f"bash -x {command}", sudo=True)
# #     log.info("Successfully executed bootstrap.sh", result)

# def extractBootstrap(node, log):
    
#     # 1. Create directory for bootstrap
#     # 2. Extract boostrap 
#     # 3. Copy geneva mockscript
#     # 4. Remove the lines from bootstrap
#     # 5. Run bootstrap

#     mkdir = node.tools[Mkdir]
#     mkdir.create_directory("/tmp/bootstrap")    
#     log.info("Create Directory /tmp/bootstrap")
    
#     ls = node.tools[Ls]
#     if(ls.path_exists("/tmp/bootstrap.tar")):
#         result = node.execute("tar -xvf /tmp/bootstrap.tar -C /tmp/bootstrap/", sudo=True)
#         log.info("Result for Extracting BootStrap:", result.stdout)

#     if(ls.path_exists("/tmp/bootstrap_geneva.sh")):
#         result = node.execute("mv /tmp/bootstrap_geneva.sh /tmp/bootstrap/drop/vmss/bootstrap_geneva.sh", sudo=True)
#         log.info(f"Moved bootstrap file : {result.stdout}")
    

#     result = node.execute("sed -i '461d' /tmp/bootstrap/drop/vmss/azfw_common.sh", sudo=True)
#     result = node.execute("sed -i '79d' /tmp/bootstrap/drop/vmss/bootstrap.sh", sudo=True)    


# def setupAzureCLI(node, log):
    
#     #download Azure-CLI
#     result = node.execute("tdnf install -y azure-cli", sudo=True)
#     log.info("Azure-CLI Download:", result.stdout)
   
#     #login to Azure-CLI
#     result = node.execute(f"az login --identity --resource-id {gsaManagedIdentity}")
#     log.info("Login to Azure-CLI:", result.stdout)
    
# def generatemdsMetadata(node, log):
    
#     ls = node.tools[Ls]
#     if (ls.path_exists("/tmp/importdatafromjson.py", sudo=True)):
#         result = node.execute("python3 /tmp/importdatafromjson.py", sudo=True)
#         log.info("Successfully generated mdsMetadata.txt", result)
#         result = node.execute(f"az login --identity --resource-id {gsaManagedIdentity}",sudo=True)
#         result = node.execute("az storage blob upload --auth-mode login --account-name lisatestresourcestorage  -c fwcreateconfigfiles -n mdsMetadata.txt -f /tmp/mdsMetadata.txt --overwrite", sudo=True)
#         log.info(f"Result for uploading mdsMetadata to blob storage: {result.stdout}")
#     else:
#         log.error(f"Can't find /tmp/importdatafromjson to generate mdsMetadata.txt file")

# def performWorkArounds(node, log):

#     # 1. Install all the required packages
#     ls = node.tools[Ls]
#     if(ls.path_exists("/tmp/install_runtime_deps.sh")):
#         result = node.execute("bash -x /tmp/install_runtime_deps.sh", sudo=True)
#         log.info("Successfully executed install_runtime_deps.sh", result.stdout)
#     else: 
#         log.error("install_runtime_deps.sh file not found")

#     # 2. Generate MSD Metadata.txt file by running script
#     # generatemdsMetadata(node,log)

#     #to-do instead of mock bring up working mdsd services
#     # 3. Setup mock_statsd.service and mdsd.service
#     node.execute("mv /tmp/mdsd.service /etc/systemd/system/mdsd.service", sudo=True)
#     node.execute("mv /tmp/mock_statsd.service /etc/systemd/system/mock_statsd.service", sudo=True)
#     node.execute("mv /tmp/mock_statsd.py /opt/mock_statsd.py", sudo=True)
#     node.execute("mv /tmp/mock_mdsd /opt/mock_mdsd", sudo=True)
#     node.execute("useradd -M -e 2100-01-01 azfwuser", sudo=True)
#     # Reload daemon 
#     result = node.execute("sudo systemctl daemon-reload", sudo=True)
#     log.info("Daemon reloaded successfully", result)
#     #Restart mdsd and mdsd.statsd service
#     result = node.execute("sudo systemctl restart mock_statsd.service", sudo=True)
#     result = node.execute("sudo systemctl restart mdsd.service", sudo=True)

#     # 4. Download psutils
#     result = node.execute("python -m ensurepip", sudo=True)
#     log.info("Successfully installed psutil", result.stdout)
#     result = node.execute('export PATH="$PATH:/home/lisatest/.local/bin"')
#     log.info("Added /home/lisatest/.local/bin to PATH", result.stdout)
#     result = node.execute(" python -m pip install psutil", sudo=True)
#     log.info("Successfully installed psutil", result.stdout)

# def verifylogrotate(node, log):
#     result =  node.execute('ls -hl /var/log | grep "syslog"',sudo=True)
#     while("syslog.1" not in result.stdout):
#         time.sleep(10)
#         result = node.execute('ls -hl /var/log | grep "syslog"',sudo=True)
#         log.info("Log Rotate kicked in and successfully created new files", result.stdout)
#     time.sleep(10)
#     result = node.execute('du -sh /var/log/syslog')
#     if ("0" not in result.stdout):
#         log.info("Rsyslog is correctly logging the files")
#     else: 
#         log.error(f"LogRotation is not successful and Rsyslog is not using new files")

# def downloadFilesFromBlob(fileName, destFileName, storageAccount, containerName, node, log):
#     blobresult = node.execute(f"az storage blob download --auth-mode login --account-name {storageAccount} -c {containerName} -n {fileName} -f /tmp/{destFileName}")
#     log.info(f"Result for download: {fileName} from Storage Account {storageAccount}, Blob Name: {containerName}/{fileName}, Result:", blobresult.stdout)
#     changePermissions(f"/tmp/{destFileName}",node)

# def changePermissions(fileName,node):
#     node.execute(f"chmod 777 {fileName}", sudo=True)

# def downloadpackages(packagename,firewallNode,log):
#     log.info("Installing package :", packagename)
#     result = firewallNode.execute(f"tdnf install -y {packagename}", sudo=True)
#     log.info("Result for installing package {}: {}".format(packagename, result.stdout))
    
# def setuppackages(servicename,firewallNode,log):
#     log.info("Enabling service :", servicename)
#     result = firewallNode.execute(f"systemctl enable {servicename}", sudo=True)
#     log.info("Result for enabling service {}: {}".format(servicename, result.stdout))
#     log.info("Starting service {}:", servicename)
#     firewallNode.execute(f"systemctl start {servicename}", sudo=True)
#     log.info("Result for starting service {}: {}".format(servicename, result.stdout))