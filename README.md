# Linux Integration Services Automation (LISA), version 2

Nov 2018

### Overview

LISAv2 is the one-stop automation solution implemented by PowerShell scripts, Linux BASH scripts and Python scripts for verifying Linux image/kernel on below platforms:
* Microsoft Azure
* Microsoft Azure Stack
* Microsoft Hyper-V
* WSL
* Ready

LISAv2 includes below test suite categories:
* Functional tests
* Performance tests
* Stress tests
* Test suites developed by Open Source communities

### Prerequisite

1. You must have a Windows Machine (Host) with PowerShell (v5.0 and above but not 6.x) as test driver. It should be Windows Server for localhost, or any Windows system including Windows 10 for remote host access case. PowerShell 6.x shows run-time error due to missing nugget.

2. You must be connected to Internet.

3. You download 3rd party software in Tools folder. If you are using secure blob in Azure Storage Account or UNC path, you can add a tag <blobStorageLocation>https://myownsecretlocation.blob.core.windows.net/binarytools</blobStorageLocation> in the secret xml file.
* 7za.exe
* dos2unix.exe
* gawk
* go1.11.4.linux-amd64.tar.gz
* golang_benchmark.tar.gz
* http_load-12mar2006.tar.gz
* jq
* plink.exe
* pscp.exe
* kvp_client32
* kvp_client64
* nc.exe
* nc64.exe

4. For running Azure tests, you must have a valid Windows Azure Subscription, if you want to enable ssh key authentication on Azure platform, please refer [here](https://docs.microsoft.com/en-us/azure/virtual-machines/linux/ssh-from-windows) for generating SSH key pairs.

5. For running Hyper-V tests, the resource requirements are:
- Hyper-V role enabled
- At least 8 GB of memory on the Host - Most of LISAv2 tests will create and start Virtual Machines (Guests) with 3.5 GB of memory assigned
- 1 External vSwitch in Hyper-V Manager/Virtual Switch Manager. This vSwitch will be named 'External' and must have an internet connection. For Hyper-V NETWORK tests you need 2 more vSwitch types created: Internal and Private. These 2 vSwitches will have the naming also 'Internal' and 'Private'.

6. For running WSL tests, you must enable WSL on the test server

    a. Open Powershell as Administrator and run:
    ```
    Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux
    ```
    b. Restart your computer when prompted.

### Download Latest Azure PowerShell

1. Download Web Platform Installer from [here](http://go.microsoft.com/fwlink/p/?linkid=320376&clcid=0x409)
2. Start Web Platform Installer and select Azure PowerShell (required 6.3.0 or above) and proceed for Azure PowerShell Installation. (Azure PowerShell version is different from PowerShell version)
3. Install the Azure Powershell Az module [here](https://docs.microsoft.com/en-us/powershell/azure/install-az-ps?view=azps-2.6.0)

### Authenticate Your Test Driver Machine with Your Azure Subscription

#### Azure AD method

This creates a 12 Hours temporary session in PowerShell. In that session, you are allowed to run Windows Azure Cmdlets to control / use your subscription.

After 12 hours you will be asked to enter username and password of your subscription again.

#### Service Principal method

Refer to this URL [here](https://docs.microsoft.com/en-us/azure/azure-resource-manager/resource-group-create-service-principal-portal)

### Prepare VHD for Your Test

> Applicable if you are uploading your own Linux VHD to Azure for test.

A VHD with Linux OS must be made compatible to work in Hyper-V environment. This includes:

* Linux Integration Services. If not available, at least KVP daemon must be running. Without KVP daemon running, the framework will not be able to obtain an IP address from the guest.
* Windows Azure Linux Agent (for testing in Azure environment only)
* SSH, and the SSH daemon configured to start on boot.
* Port 22 open in the firewall
* A regular user account on the guest OS
> "root" user cannot be used in the test configuration

Please follow the steps mentioned at [here](https://docs.microsoft.com/en-us/azure/virtual-machines/linux/create-upload-generic)

### Launch Test Suite

1. Clone this automation code to your test system by:

          git clone https://github.com/LIS/LISAv2.git

2. Create a new secret file, or update it with those required fields from .\XML\GlobalConfigurations.xml manually for the preparation:

    2.1 Update below subscription info using created service principal, can use [this script](https://github.com/LIS/LISAv2/blob/master/Utilities/CreateServicePrincipal.ps1) to create service principal.
        For example, if you run test case in location 'eastasia', then you create a standard and premium storage account under the test subscription in 'eastasia' and replace storage account names in secrets file.
        If you run against other regions, add new tag sections like <new_region></new_region>
    ```xml
        <secrets>
            <!--Not mandatory-->
            <SubscriptionName>Enter your subscription name</SubscriptionName>
            <!--Below four sections are mandatory when test against Azure platform-->
            <SubscriptionID>Enter your subscription id</SubscriptionID>
            <SubscriptionServicePrincipalTenantID>Enter a new Tenant id from CreateServicePrincipal.ps1 result</SubscriptionServicePrincipalTenantID>
            <SubscriptionServicePrincipalClientID>Enter a new Client id from CreateServicePrincipal.ps1 result</SubscriptionServicePrincipalClientID>
            <SubscriptionServicePrincipalKey>Enter a new Principal key from CreateServicePrincipal.ps1 result<SubscriptionServicePrincipalKey>
            <!--Download needed tools from the blob-->
            <blobStorageLocation>Enter your blob storage location if needed</blobStorageLocation>
            <!--VMs Credential-->
            <linuxTestUsername>Enter Linux VM user name</linuxTestUsername>
            <linuxTestPassword>Enter Linux VM user password with high complexity</linuxTestPassword>
            <sshPrivateKey>Downloadable URL or local file - ssh ppk private key</sshPrivateKey>
            <!--Database info for upload results-->
            <DatabaseServer></DatabaseServer>
            <DatabaseUser></DatabaseUser>
            <DatabasePassword></DatabasePassword>
            <DatabaseName></DatabaseName>
            <RegionAndStorageAccounts>
                <eastasia>
                    <StandardStorage>Enter Standard Storage Account name</StandardStorage>
                    <PremiumStorage>Enter Premium Storage Account name</PremiumStorage>
                </eastasia>
                <westus>
                    <StandardStorage>Enter Standard Storage Account name</StandardStorage>
                    <PremiumStorage>Enter Premium Storage Account name</PremiumStorage>
                </westus>
                <!--Other locations sections-->
            </RegionAndStorageAccounts>
        </secrets>
    ```

    2.2 Update the .\XML\GlobalConfigurations.xml file with your Azure subscription information or Hyper-V host information:

        Go to Global > Azure/HyperV and update following fields:

            a. SubscriptionID
            b. SubscriptionName (Optional)
            c. ManagementEndpoint
            d. Environment (For Azure PublicCloud, use `AzureCloud`)
            e. ARMStorageAccount

        Example:

    ```xml

        <Azure>
            <Subscription>
                <SubscriptionID>2cd20493-0000-1111-2222-0123456789ab</SubscriptionID>
                <SubscriptionName>YOUR_SUBSCRIPTION_NAME</SubscriptionName>
                <ManagementEndpoint>https://management.core.windows.net</ManagementEndpoint>
                <Environment>AzureCloud</Environment>
                <ARMStorageAccount>ExistingStorage_Standard</ARMStorageAccount>
            </Subscription>
        </Azure>
        <HyperV>
            <Hosts>
                <Host>
                    <!--ServerName can be localhost or Hyper-V host name-->
                    <ServerName>localhost</ServerName>
                    <DestinationOsVHDPath>VHDs_Destination_Path</DestinationOsVHDPath>
                </Host>
                <Host>
                    <!--If run test against 2 hosts, set ServerName as another host computer name-->
                    <ServerName>lis-01</ServerName>
                    <!--If run test against 2 hosts, DestinationOsVHDPath is mandatory-->
                    <DestinationOsVHDPath>D:\vhd</DestinationOsVHDPath>
                </Host>
            </Hosts>
        </HyperV>
        <WSL>
            <Hosts>
                <Host>
                    <!--The name of the WSL host, which can be local or remote -->
                    <ServerName>localhost</ServerName>
                    <!--The destination path to extract the distro package on the WSL host-->
                    <DestinationOsVHDPath></DestinationOsVHDPath>
                </Host>
                <Host>
                    <ServerName>localhost</ServerName>
                    <DestinationOsVHDPath></DestinationOsVHDPath>
                </Host>
            </Hosts>
        </WSL>
    ```

3. There are two ways to run LISAv2 tests:

   a. Provide all parameters to Run-LisaV2.ps1

        .\Run-LisaV2.ps1 -TestPlatform "Azure" -TestLocation "<Region location>" -RGIdentifier "<Identifier of the resource group>" [-ARMImageName "<publisher offer SKU version>" | -OsVHD "<VHD from storage account>" ] [[-TestCategory "<Test Catogry from Jenkins pipeline>" | -TestArea "<Test Area from Jenkins pipeline>"]* | -TestTag "<A Tag from Jenkins pipeline>" | -TestNames "<Test cases separated by comma>"]
        Basic Azure platform example:
        .\Run-LisaV2.ps1 -TestPlatform "Azure" -TestLocation "westus" -RGIdentifier "deployment" -ARMImageName "canonical ubuntuserver 18.04-lts Latest" -TestNames "VERIFY-DEPLOYMENT-PROVISION"
        Azure platform using secret file:
        .\Run-LisaV2.ps1 -TestPlatform "Azure" -TestLocation "westus" -RGIdentifier "deployment" -ARMImageName "canonical ubuntuserver 18.04-lts Latest" -TestNames "VERIFY-DEPLOYMENT-PROVISION" -XMLSecretFile "E:\AzureCredential.xml"

        .\Run-LisaV2.ps1 -TestPlatform "HyperV" [-TestLocation "ServerName"] -RGIdentifier "<Identifier of the vm group>" -OsVHD "<local or UNC path or downloadable URL of VHD>" [[-TestCategory "<Test Catogry from Jenkins pipeline>" | -TestArea "<Test Area from Jenkins pipeline>"]* | -TestTag "<A Tag from Jenkins pipeline>" | -TestNames "<Test cases separated by comma>"]
        HyperV platform examples:
        .\Run-LisaV2.ps1 -TestPlatform "HyperV" -RGIdentifier "ntp" -OsVHD 'E:\vhd\ubuntu_18_04.vhd' -TestNames "TIMESYNC-NTP"
        .\Run-LisaV2.ps1 -TestPlatform "HyperV" -RGIdentifier "ntp" -OsVHD 'http://www.somewebsite.com/vhds/ubuntu_18_04.vhd' -TestNames "TIMESYNC-NTP"

        .\Run-LisaV2.ps1 -TestPlatform "WSL" [-TestLocation "<WSL host name>"] -RGIdentifier "<Identifier for the test run>" -OsVHD "<local path or public URL>" [-DestinationOsVHDPath "<destination path on WSL host>"] [[-TestCategory "<Test Catogry from Jenkins pipeline>" | -TestArea "<Test Area from Jenkins pipeline>"]* | -TestTag "<A Tag from Jenkins pipeline>" | -TestNames "<Test cases separated by comma>"]
         WSL platform example:
        .\Run-LisaV2.ps1 -TestPlatform WSL -TestLocation "localhost" -RGIdentifier 'ubuntuwsl' -TestNames "VERIFY-BOOT-ERROR-WARNINGS" -OsVHD 'https://aka.ms/wsl-ubuntu-1804' -DestinationOsVHDPath "D:\test"

        Custom Parameters example:
        .\Run-LisaV2.ps1 -TestPlatform "Azure" -TestLocation "<Region location>" -RGIdentifier "<Identifier of the resource group>" [-ARMImageName "<publisher offer SKU version>" | -OsVHD "<VHD from storage account>" ] [[-TestCategory "<Test Catogry from Jenkins pipeline>" | -TestArea "<Test Area from Jenkins pipeline>"]* | -TestTag "<A Tag from Jenkins pipeline>" | -TestNames "<Test cases separated by comma>"] -CustomParameters "TiPCluster=<cluster name> | TipSessionId=<Test in Production ID> |  DiskType=Managed/Unmanaged | Networking=SRIOV/Synthetic | ImageType=Specialized/Generalized | OSType=Windows/Linux"
        Nested Azure VM example:
        .\Run-LisaV2.ps1 -TestPlatform "Azure" -TestLocation "westus" -RGIdentifier "deployment" -ARMImageName "MicrosoftWindowsServer WindowsServer 2016-Datacenter latest" -TestNames "NESTED-HYPERV-NTTTCP-DIFFERENT-L1-PUBLIC-BRIDGE" -CustomeParameters "OSType=Windows"

        Multiple override virtual machine size example:
        .\Run-LisaV2.ps1 -TestPlatform "Azure" -TestLocation "westus" -RGIdentifier "deployment" -ARMImageName "canonical ubuntuserver 18.04-lts Latest" -TestNames "VERIFY-DEPLOYMENT-PROVISION" -OverrideVMSize "Standard_A2,Standard_DS1_v2"

        Ready platform example:
        .\Run-LisaV2.ps1 -TestPlatform "Ready" -RGIdentifier "10.100.100.100:1111;10.100.100.100:1112" -TestNames "<Test cases separated by comma>" -XMLSecretFile "E:\AzureCredential.xml" [-EnableTelemetry]

   b. Provide parameters in .\XML\TestParameters.xml.

        .\Run-LisaV2.ps1 -TestParameters .\XML\TestParameters.xml

   Note: Please refer .\XML\TestParameters.xml file for more details.

### More Information

For more details, please refer to the documents [here](https://github.com/LIS/LISAv2/blob/master/Documents/How-to-use.md).

Contact: <lisasupport@microsoft.com>
