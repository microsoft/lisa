# Linux Integration Services Automation (LISA), version 2

June 2020

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

### Authenticate from LISAv2 Orchestrator Machine with Your Azure Subscription
* Sign in with Azure PowerShell

Refer to this URL [here](https://docs.microsoft.com/en-us/powershell/azure/authenticate-azureps)

* Prepare Service Principal and create secret file

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

2. Create a new secret xml file, and update required fields from .\XML\GlobalConfigurations.xml:

    2.1 Secret File to be used by `-XMLSecretFile <Path of Secret File>` when Run-LISAv2.ps1
     - If Run LISAv2 for Azure Platform with authentication from service principal, please update created service principal info in your secrete file, can use [this script](https://github.com/LIS/LISAv2/blob/master/Utilities/CreateServicePrincipal.ps1) to create service principal.
	 - If Run-LISAv2.ps1 for Azure Platform from an authenticated PowerShell session (check `Get-AzContext` from PowerShell), no need prepare Service Principla info in your secrete file.
	 - Storage Accounts Tips:
        *   If you want LISAv2 to create all potential needed Azure storage accouts from all available Azure regions that supports `'Microsoft.Storage'` resource type and keep using those storage accounts in the following automation or ad-hoc testing, give `<ARMStorageAccount>Auto_Complet_RG=Xxx</ARMStorageAccount>` from .\XML\GlobalConfigurations.xml, or you can specify `-StorageAccount "Auto_Complet_RG=Xxx"` during Run-LISAv2.ps1.
	        * `'Xxx'` is the Resource Group Name to host storage accounts which are used for LISAv2 execution. If Azure resource group `'Xxx'` does not exist, LISAv2 will create `'Xxx'` resource group automatically.
	        * LISAv2 will create new storage accounts automatically with name following regular expression `lisa[a-z0-9]{15}`, and make sure there are two storage accounts (one is `Standard_LRS` type, another is `Premium_LRS` type) created (or checked for existence) in Azure resource group `'Xxx'` for each Azure region which supports `'Microsoft.Storage'` resource type. Any existing storage account that follows the naming format `lisa[a-z0-9]{15}` from Azure resource group `'Xxx'` will be taken as expected storage accounts and LISAv2 will not create duplicate storage accounts with same storage account type (`Standard_LRS` or `Premium_LRS`) at the same region.
	        * LISAv2 will update `<RegionAndStorageAccounts>` of user specified secret file with expected storage accounts from Azure resource group `'Xxx'` for the following execution, just as user created those storage accounts manually and replaced in secret file as below example.
	        * If user changes to another Azure resource group `'Yyy'` instead of `'Xxx'` used previously when Run-LISAv2 with the same subscription, LISAv2 will create (or check existence of) another set of storage accounts with naming `lisa[a-z0-9]{15}` in Azure resource group `'Yyy'`. So note about this, and think over before changing to another resource group in the following automation or ad-hoc testing.
        *   If you already prepared standard and premium storage accounts in your test subscription for your test location, e.g., `'eastasia'`, please replace storage account names in secret file as below. If you may run against other regions, add more tag elements like `<other_region></other_region>`.
    ```xml
        <secrets>
            <!--Not mandatory-->
            <SubscriptionName>Enter your subscription name</SubscriptionName>
            <!--'SubscriptionID' is manadatory if 'SubscriptionID' is empty/invalid from .\XML\GlobalConfigurations.xml, otherwise, it's optional-->
            <SubscriptionID>Enter your subscription id</SubscriptionID>
            <!--Below three elements are mandatory if testing against Azure platform with service principal, otherwise they are optional (e.g., Signing in with Azure PowerShell before Run-LISAv2.ps1)-->
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
            <!--Below <RegionAndStorageAccounts> is optional when <ARMStorageAccount> is set with 'Auto_Complete_RG=Xxx' from .\XML\GlobalConfigurations.xml-->
            <!--Below <RegionAndStorageAccounts> is optional when run LISAv2 in Windows PowerShell with parameter '-StorageAccount "Auto_Complete_RG=Xxx"'-->
            <!-- 'Xxx' is the Resource Group Name to host all the storage accounts, if 'Xxx' is not exist, LISAv2 will create resource group automatically and will create storage accounts in that resource group for all available regions-->
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

    2.2 Update .\XML\GlobalConfigurations.xml file is optional, depending on your [authentication options](https://github.com/LIS/LISAv2#authenticate-from-lisav2-orchestrator-machine-with-your-azure-subscription) and how you have prepared the secrets file. But in some cases, you may need to update .\XML\GlobalConfigurations.xml with your Azure subscription information or Hyper-V host information:

        Go to Global > Azure/HyperV and update following fields if necessary:

            a. SubscriptionID
            b. SubscriptionName (Optional)
            c. Environment (For Azure PublicCloud, use `AzureCloud`)
            d. ARMStorageAccount
            e. DefaultARMImageName

        Example:

    ```xml

        <Azure>
            <Subscription>
                <!--This 'SubscriptionID' is mandatory if 'SubscriptionID' is empty/invalid from the secret xml file, which is indicated by '-XMLSecretFile' when Run-LISAv2.ps1, otherwise, it's optional -->
                <SubscriptionID>2cd20493-0000-1111-2222-0123456789ab</SubscriptionID>
                <SubscriptionName>YOUR_SUBSCRIPTION_NAME</SubscriptionName>
                <Environment>AzureCloud</Environment>
                <!--This 'ARMStorageAccount' is mandatory if '-StorageAccount' is not specified when Run-LISAv2.ps1, otherwise, it's optional-->
                <ARMStorageAccount>ExistingStorage_Standard</ARMStorageAccount>
            </Subscription>
            <!--This 'DefaultARMImageName' is the default value for '-ARMImageName' from Azure Gallery, when '-OsVHD' and '-ARMImageName' both are not specified form Run-LISAv2 test parameters-->
            <DefaultARMImageName>Canonical UbuntuServer 18.04-LTS Latest</DefaultARMImageName>
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
  * Note when testing with 'Azure' platform:

    * `-ARMImageName` is optional when testing with Azure Gallery Images (`-OsVHD` is used for testing with custom image). If both `-ARMImageName` and `-OsVHD` are not provided from Run-LISAv2.ps1 parameters, LISAv2 will try to use `<DefaultARMImageName>` from .\XML\GlobalConfigurations.xml as value of `-ARMImageName`. In this case, if `<DefaultARMImageName>` is not defined from `.\XML\GlobalConfigurations.xml`, exeption will be thrown.

    * `-TestLocation` is optional. If `-TestLocation` is not provided from Run-LISAv2.ps1 parameters, LISAv2 will use the pre-defined `<TestLocation>` from test definition xml for each test case. If test case does not have any specific `<TestLocation>`, LISAv2 will choose an Azure Region automatically per test case Vm Size and Vm Family from current subscription context. The auto-selected TestLocation (Azure Region) is likely to have the most available vCPUs Compute resources for the target Vm Size and Vm Family of current test case. The available vCPU resources of all enabled Azure Regions is calculated and ordered by LISAv2 dynamically based on the current Compute vCPUs resource usage of current subscription when necessary. Run-LISAv2 without `-TestLocation` can be used when Compute resources for testing VM Sizes are not coming from single Azure Region, but distributed from different Azure Regions, in that case, running selected test cases all in once of LISAv2 execution is possible. If the target VM Size is not enabled from any region of current subscription, LISAv2 will report exception. If LISAv2 could not deploy a target Vm Size due to vCPUs Compute resource is not enough temporarily, LISAv2 will wait for at most 1 hour for any released Compute resources, and then continue the testing when resources getting available, or abort the current test case when waiting timeout.

    * If a test case has pre-defined SetupConfig values for `<ARMImanageName>`, `<OverrideVMSize>`, `<TestLocation>` in test definition xml, those settings will be respected in LISAv2 environment(VM) privisioning stage before any testing script being invoked. The pre-defined SetupConfig value in the test definition xml should be a Comma-Separated string for multiple elements (no comma when it only has one element). Each element in the comma-seperated string can be literal matching form (no `=~` prefix) or regex matching form with `=~` prefix. E.g., `<OverrideVMSize>Standard_DC2s_v2,=~Standard_DC[0-9]+s_v2</OverrideVMSize>`. If no custom parameters from Run-LISAv2 commandline and no default value (e.g., default of ARMImageName in `.\XML\GlobalConfigurations.xml`) configured, those pre-defined SetupConfig value elements which doesn't prefixed by `=~` will be applied automatically to run againt the corresponding defined test case. If user wants to apply CustomParameters of LISAv2 to selected test cases forcibly, the switch parameter `-ForceCustom` can be used in this scenario. Specifically, `-ForceCustom` will take whatever provided from Run-LISAv2 parameters of `-ArmImageName`, `-TestLocation`, `-OverrideVMSize` and force override the pre-defined settings in each selected test cases, no matter these SetupConfig elements are defined or not in each test cases. `-ForceCustom` is generally an optional parameter to Run-LISAv2 in most scenarios, if test cases have been well defined, user does not need to use it, but it may be useful when user wants to make LISAv2 pipeline configurations backward compatible to the tesitng requirements, especially when test cases are not always well-defined. What's a proper defined test cases? For example, this test case is by default using ARMImageName `RedHat RHEL 78-gen2 latest`, but actually it can be tested with any RedHat RHEL distro images from Azure gallery, meanwhile, all other distro images are meaningless to use this test case, then it should be defined as `<ARMImageName>RedHat RHEL 78-gen2 latest,=~RHEL</ARMImageName>` from its `<SetupConfig>` element in the definition xml.

    * Test Cases which is selected by `-TestCategory`, `-TestPriority`, `-TestArea`, `-TestTag`, `-TestSetup`, can be tested with expandable setup parameters, such as `-ARMImageName "<publisher  offer  SKU  version>(,<publisher  offer  SKU  version>)..."`, `-OverrideVMSize "<Azure_Vm_Size>(,<Azure_Vm_Size>)..."`, `-TestLocation "<Azure_Region>(,<Azure_Region>)..."`. Same as pre-defined SetupConfig from test definition xml, these setup parameters from Run-LISAv2 commandline can be Comma-Separated value string (only literal value elements without `=~` prefix will be applied), which means the selected test cases are intended to be tested multiple times with different ARMImageNames, different Vm Sizes, or different TestLocations (Azure Regions). If Comma-Separated values used in `-ARMImageName` `-OverrideVMSize`, `-TestLocation`, the overall mixed test case execution count will be: (Count of Selected Test Cases) * (Count of ARMImageNames) * (Count of TestLocations/Regions) * (Count of OverrideVMSizes) * (Number of TestIterations).

    * The test parameters of `-ARMImageName`, `-TestLocation`, `-OverrideVMSize` are semantically equivalent to be used as CustomParameters like `'Network=xxx;OSType=yyy;DiskType=mmm;ImageType=nnn'`. For example, `-ARMImageName "Redhat RHEL 7.7 Latest,Canonical UbuntuServer 18.04-LTS Latest"` has the same effect as `-CustomParameters "ARMImageName=Redhat RHEL 7.7 Latest,Canonical UbuntuServer 18.04-LTS Latest"` in LISAv2.

    * The switch test parameters `-RunInParallel` will start multiple processes to Run-LISAv2 in parallel on Azure platform. By default, the number of LISAv2 jobs in parallel will be 'numberoflogicalprocessors' of the current Orchestrator machine (or vCPU number of the Orchestrator VM) divided by 2. Another optional parameter `-TotalCountInParallel` can be used to set the expected processes total count, if user does not prefer the default value. Note, other platforms except Azure may not support `-RunInParallel` successfully, because they may depends on various specific platform settings.

   a. Provide all parameters to Run-LisaV2.ps1

        .\Run-LisaV2.ps1 -TestPlatform "Azure" [-TestLocation "<Azure Region>(,<Azure Region>)..."] -RGIdentifier "<Identifier of the resource group>" [-ARMImageName "<publisher offer SKU version>(,<publisher offer SKU version>)..." | -OsVHD "<VHD from storage account>" ] [OverrideVMSize "<Azure_Vm_Size>(,<Azure_Vm_Size>)..."] [[-TestCategory "<Test Catogry from Jenkins pipeline>" | -TestArea "<Test Area from Jenkins pipeline>"]* | -TestTag "<A Tag from Jenkins pipeline>" | -TestNames "<Test cases separated by comma>"]"

        Basic Azure platform example:
        .\Run-LisaV2.ps1 -TestPlatform "Azure" -TestLocation "westus" -RGIdentifier "deployment" -ARMImageName "canonical ubuntuserver 18.04-lts Latest" -TestNames "VERIFY-DEPLOYMENT-PROVISION"
        Azure platform using secret file:
        .\Run-LisaV2.ps1 -TestPlatform "Azure" -TestLocation "westus" -RGIdentifier "deployment" -ARMImageName "canonical ubuntuserver 18.04-lts Latest" -TestNames "VERIFY-DEPLOYMENT-PROVISION" -XMLSecretFile "E:\AzureCredential.xml"
        Azure platform using default ARMImageName and auto-selected TestLoacation:
        .\Run-LisaV2.ps1 -TestPlatform "Azure" -RGIdentifier "deployment" -TestNames "VERIFY-DEPLOYMENT-PROVISION" -XMLSecretFile "E:\AzureCredential.xml"
        Azure platform using Comma-Separated ARMImageName, OverrideVMSize, TestLoacation and TestIterations to test multiple times for selected test cases:
        .\Run-LisaV2.ps1 -TestPlatform "Azure" -RGIdentifier "deployment" -TestLocation "westus,eastus2" -ARMImageName "canonical ubuntuserver 18.04-lts Latest,Redhat RHEL 7.7 Latest" -OverrideVMSize "Standard_D2s_v2,Standard_D15s_v2" -TestIterations 2 -TestNames "VERIFY-DEPLOYMENT-PROVISION" -XMLSecretFile "E:\AzureCredential.xml"

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

        'Ready' platform relies on '-TestLocation' to provide the locations of test environment, then LISAv2 will skip deployment step for selected test cases. TestLocation of Read platform should follow this Comma-Separated format: `<public_ip_address_a>:<ssh_port_a>,<public_ip_address_b>:<ssh_port_b>`
        Ready platform example:
        .\Run-LisaV2.ps1 -TestPlatform "Ready" -TestLocation "10.100.100.100:1111,10.100.100.100:1112" -TestNames "<Test cases separated by comma>" -XMLSecretFile "E:\AzureCredential.xml" [-EnableTelemetry]

   b. Provide parameters in .\XML\TestParameters.xml.

        .\Run-LisaV2.ps1 -TestParameters .\XML\TestParameters.xml

   Note: Please refer .\XML\TestParameters.xml file for more details.

### More Information

For more details, please refer to the documents [here](https://github.com/LIS/LISAv2/blob/master/Documents/How-to-use.md).

Contact: <lisasupport@microsoft.com>

## Contributing

This project welcomes contributions and suggestions. Most contributions require
you to agree to a Contributor License Agreement (CLA) declaring that you have
the right to, and actually do, grant us the rights to use your contribution. For
details, visit https://cla.opensource.microsoft.com.

When you submit a pull request, a CLA bot will automatically determine whether
you need to provide a CLA and decorate the PR appropriately (e.g., status check,
comment). Simply follow the instructions provided by the bot. You will only need
to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of
Conduct](https://opensource.microsoft.com/codeofconduct/). For more information
see the [Code of Conduct
FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or contact
[opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional
questions or comments.
