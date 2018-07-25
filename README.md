# Linux Integration Services Automation (LISA), version 2

July 2018

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
          
2. Update the GlobalConfigurations.xml file with your Azure subscription infomation: 

   Go to Global > Azure  and update following fields :

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

```

3. Run the test suite with below command:

        .\RunTests.ps1 -TestPlatform "Azure" -TestLocation "<Region location>" -RGIdentifier "<Identifier of the resource group>" [-ARMImageName "<publisher offer SKU version>" | -OsVHD "<VHD from storage account>" ] [[-TestCategory "<Test Catogry from Jenkins pipeline>" | -TestArea "<Test Area from Jenkins pipeline>"]* | -TestTag "<A Tag from Jenkins pipeline>" | -TestNames "<Test cases separated by comma>"]

### More Information

For more details, please refer to the documents [here](https://github.com/LIS/LISAv2/blob/master/Documents/How-to-use.md).

Contact: <lisasupport@microsoft.com>
