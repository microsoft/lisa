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

1. You must have a Windows Machine (Host) with PowerShell (v5.0 and above) as test driver. It should be Windows Server for localhost, or any Windows system including Windows 10 for remote host access case.

2. You must be connected to Internet.

3. You download 3rd party software in Tools folder. If you are using secure blob in Azure Storage Account or UNC path, you can add a tag <blobStorageLocation>https://myownsecretlocation.blob.core.windows.net/binarytools</blobStorageLocation> in any secret xml file.
* 7za.exe
* dos2unix.exe
* gawk
* jq
* plink.exe
* pscp.exe
* kvp_client32
* kvp_client64
* nc.exe

4. For running Azure tests, you must have a valid Windows Azure Subscription.

5. For running Hyper-V tests, the resource requirements are:
- Hyper-V role enabled
- At least 8 GB of memory on the Host - Most of lisav2 tests will create and start Virtual Machines (Guests) with 3.5 GB of memory assigned
- 1 External vSwitch in Hyper-V Manager/Virtual Switch Manager. This vSwitch will be named 'External' and must have an internet connection. For Hyper-V NETWORK tests you need 2 more vSwitch types created: Internal and Private. These 2 vSwitches will have the naming also 'Internal' and 'Private'.

### Download Latest Azure PowerShell

1. Download Web Platform Installer from [here](http://go.microsoft.com/fwlink/p/?linkid=320376&clcid=0x409)
2. Start Web Platform Installer and select Azure PowerShell (required 6.3.0 or above) and proceed for Azure PowerShell Installation.

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

1. Clone this automation code to your test driver by:

          git clone https://github.com/LIS/LISAv2.git

2. Update the .\XML\GlobalConfigurations.xml file with your Azure subscription information or Hyper-V host information:

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
                <!--ServerName can be localhost or Hyper-V host name-->
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
