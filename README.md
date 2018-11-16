# Linux Integration Services Automation (LISA), version 2

Nov 2018

### Overview

LISAv2 is the one-stop automation solution implemented by PowerShell scripts, Linux BASH scripts and Python scripts for verifying Linux image/kernel on below platforms:
* Microsoft Azure
* Microsoft Azure Stack
* Microsoft Hyper-V

LISAv2 includes below test suite categories:
* BVT tests
* Smoke tests
* Functional tests
* Performance tests
* Test suites developed by Open Source communities

### Prerequisite

1. You must have a Windows Machine with PowerShell (v5.0 and above) as test driver.

2. You must be connected to Internet.

3. You must have a valid Windows Azure Subscription.

4. You download 3rd party software in Tools folder. If you are using secure blob in Azure Storage Account or UNC path, you can add a tag <blobStorageLocation></blobStorageLocation> in any secret xml file.
* 7za.exe
* dos2unix.exe
* gawk
* jq
* plink.exe
* pscp.exe
* kvp_client32
* kvp_client64
* nc.exe

### Download Latest Azure PowerShell

1. Download Web Platform Installer from [here](http://go.microsoft.com/fwlink/p/?linkid=320376&clcid=0x409)
2. Start Web Platform Installer and select Azure PowerShell (Recommend 6.0.0 or above) and proceed for Azure PowerShell Installation.

### Authenticate Your Test Driver Machine with Your Azure Subscription

#### Azure AD method

This creates a 12 Hours temporary session in PowerShell. In that session, you are allowed to run Windows Azure Cmdlets to control / use your subscription.

After 12 hours you will be asked to enter username and password of your subscription again.

#### Service Principal method

Refer to this URL [here](https://docs.microsoft.com/en-us/azure/azure-resource-manager/resource-group-create-service-principal-portal)

### Prepare VHD for Your Test

> Applicable if you are uploading your own Linux VHD to Azure for test.

A VHD with Linux OS must be made compatible to work in HyperV environment. This includes:

* Linux Integration Services
* Windows Azure Linux Agent (for testing in Azure environment only)

Please follow the steps mentioned at [here](https://docs.microsoft.com/en-us/azure/virtual-machines/linux/create-upload-generic)

### Launch Test Suite

1. Clone this automation code to your test driver by:

          git clone https://github.com/LIS/LISAv2.git

2. Update the .\XML\GlobalConfigurations.xml file with your Azure subscription information or HyperV host information:

   Go to Global > Azure/HyperV and update following fields :

        a. SubscriptionID
        b. SubscriptionName (Optional)
        c. ManagementEndpoint
        d. Environment (For Azure PublicCloud, use `AzureCloud`)
        e. ARMStorageAccount

   Example :

```xml

  <Azure>
        <Subscription>
            <SubscriptionID>2cd20493-0000-1111-2222-0123456789ab</SubscriptionID>
            <SubscriptionName>YOUR_SUBSCRIPTION_NAME</SubscriptionName>
            <ManagementEndpoint>https://management.core.windows.net</ManagementEndpoint>
            <Environment>AzureCloud</Environment>
            <ARMStorageAccount>ExistingStorage_Standard</ARMStorageAccount>
        </Subscription>

  <HyperV>
        <Hosts>
            <Host>
                <!--ServerName can be localhost or HyperV host name-->
                <ServerName>localhost</ServerName>
                <SourceOsVHDPath></SourceOsVHDPath>
                <DestinationOsVHDPath>VHDs_Destination_Path</DestinationOsVHDPath>
            </Host>
            <Host>
                <!--If run test against 2 hosts, set ServerName as another host computer name-->
                <ServerName>lis-01</ServerName>
                <SourceOsVHDPath></SourceOsVHDPath>
                <!--If run test against 2 hosts, DestinationOsVHDPath is mandatory-->
                <DestinationOsVHDPath>D:\vhd</DestinationOsVHDPath>
            </Host>
        </Hosts>
```

3. There are two ways to run LISAv2 tests:

   a. Provide all parameters to Run-LisaV2.ps1

        .\Run-LisaV2.ps1 -TestPlatform "Azure" -TestLocation "<Region location>" -RGIdentifier "<Identifier of the resource group>" [-ARMImageName "<publisher offer SKU version>" | -OsVHD "<VHD from storage account>" ] [[-TestCategory "<Test Catogry from Jenkins pipeline>" | -TestArea "<Test Area from Jenkins pipeline>"]* | -TestTag "<A Tag from Jenkins pipeline>" | -TestNames "<Test cases separated by comma>"]
        Example:
        .\Run-LisaV2.ps1 -TestPlatform "Azure" -TestLocation "westus" -RGIdentifier "deployment" -ARMImageName "canonical ubuntuserver 18.04-lts Latest" -TestNames "BVT-VERIFY-DEPLOYMENT-PROVISION"

        .\Run-LisaV2.ps1 -TestPlatform "HyperV" [-TestLocation "ServerName"] -RGIdentifier "<Identifier of the vm group>" -OsVHD "<local or UNC path>" [[-TestCategory "<Test Catogry from Jenkins pipeline>" | -TestArea "<Test Area from Jenkins pipeline>"]* | -TestTag "<A Tag from Jenkins pipeline>" | -TestNames "<Test cases separated by comma>"]
        Example:
        .\Run-LisaV2.ps1 -TestPlatform "HyperV" -RGIdentifier "ntp" -OsVHD 'E:\vhd\ubuntu_18_04.vhd' -TestNames "BVT-CORE-TIMESYNC-NTP"

   b. Provide parameters in .\XML\TestParameters.xml.

        .\Run-LisaV2.ps1 -TestParameters .\XML\TestParameters.xml

   Note: Please refer .\XML\TestParameters.xml file for more details.

### More Information

For more details, please refer to the documents [here](https://github.com/LIS/LISAv2/blob/master/Documents/How-to-use.md).

Contact: <lisasupport@microsoft.com>
