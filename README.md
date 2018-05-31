# Test Automation for Microsoft Linux on Azure & Hyper-V

Automation platform for Linux images testing on Microsoft Azure and Hyper-V

## Overview

LISAv2 (Linux Integrated Service Automation) is the One-stop automation solution for Linux images/kernel testing on Microsoft Azure and Hyper-V. LISA-v2 supports both Microsoft Azure and Hyper-V automation, and they use PowerShell, BASH and python scripts. It includes feature, performance, stress and regression tests about new Linux Operating Systems and Kernels. The test suite provides Build Verification Tests (BVTs), Azure VNET Tests and Network tests also.

### Prerequisite

1. You must have a Windows Machine with PowerShell. Tested Platforms:

          a.  Windows 8x64
          b.  Windows 10x64
          c.  Server 2012
          d.  Server 2012 R2
          e.  Server 2016

2. You must be connected to Internet.
3. You must have a valid Windows Azure Subscription.

          a.  Subscription Name
          b.  Subscription ID

### Download Latest Automation Code

1. Checkout from https://github.com/LIS/LISAv2.git to your local storage or folk to your GitHub account.

### Download Latest Azure PowerShell

1. Download Web Platform Installer from [here](http://go.microsoft.com/fwlink/p/?linkid=320376&clcid=0x409) 
2. Start Web Platform Installer and select Azure PowerShell (Recommend 6.0.0 or above) and proceed for Azure PowerShell Installation.

### Authenticate Your Machine with Your Azure Subscription

1. Azure AD method

        This creates a 12 Hours temporary session in PowerShell, in that session, you are allowed to run Windows Azure Cmdlets to control / use your subscription. After 12 hours you will be asked to enter username and password of your subscription. This may create problems long running automations, hence we use service principal method.

2. Service Principal method

        Refer to this URL [here](https://docs.microsoft.com/en-us/azure/azure-resource-manager/resource-group-create-service-principal-portal)

### Update GlobalConfigurations.xml file

1. Setup Subscription details.

      Go to Global > Azure  and update following fields :

        a. SubscriptionID
        b. SubscriptionName
        c. ManagementEndpoint
        d. Environment
        e. ARMStorageAccount

  Example :

```xml

  <Azure>
        <Subscription>
            <SubscriptionID>2cd20493-fe97-42ef-9ace-ab95b63d82c4</SubscriptionID>
            <SubscriptionName>YOUR_SUBSCRIPTION_NAME</SubscriptionName>
            <ManagementEndpoint>https://management.core.windows.net</ManagementEndpoint>
            <Environment>AzureCloud</Environment>
            <ARMStorageAccount>ExistingStorage_Standard</ARMStorageAccount>
        </Subscription>

```

2. Save files.

### Prepare VHD to work in Azure

`Applicable if you are uploading your own VHD with Linux OS to Azure.`

A VHD with Linux OS must be made compatible to work in Azure environment. This includes �

        1. Installation of Linux Integration Services to Linux VM (if already not present)
        2. Installation of Windows Azure Linux Agent to Linux VM (if already not installed.)
        3. Installation of minimum required packages. (Applicable if you want to run Tests using Automation code)

Please follow the steps mentioned at [here](https://docs.microsoft.com/en-us/azure/virtual-machines/linux/create-upload-generic)

### Prepare VHD to work with Automation code

`Applicable if you are using already uploaded VHD / Platform Image to run automation.`

To run automation code successfully, below are the required packages in your Linux VHD.

        1. iperf
        2. mysql-server
        3. mysql-client
        4. gcc
        5. gcc-c++
        6. bind
        7. bind-utils
        8. bind9
        9. python
        10. python-pyasn1
        11. python-argparse
        12. python-crypto
        13. python-paramiko
        14. libstdc++6
        15. psmisc
        16. nfs-utils
        17. nfs-common
        18. tcpdump

### How to Start Automation

Before starting Automation, make sure that you have completed steps in chapter [Prepare Your Machine for Automation Cycle](#prepare)

        1. Start PowerShell with Administrator privileges
        2. Navigate to folder where automation code exists
        3. Issue automation command

#### Automation Cycles Available

        1. BVT
        2. PERFORMANCE
        3. FUNCTIONAL
        4. COMMUNITY
        5. SMOKE

#### Supported Azure Mode

        - AzureResourceManager, if the value is present in the SupportedExecutionModes tag of the case definition

#### Command to Start any of the Automation Cycle

        .\RunTests.ps1 -TestPlatform "Azure" -TestLocation "<Region location>" -RGIdentifier "<Identifier of the resource group>" [-ARMImageName "<publisher offer SKU version>" | -OsVHD "<VHD from storage account>" ] [[-TestCategory "<Test Catogry from Jenkins pipeline>" | -TestArea "<Test Area from Jenkins pipeline>"]* | -TestTag "<A Tag from Jenkins pipeline>" | -TestNames "<Test cases separated by comma>"]

#### More Information

For more details, please refer to the documents [here](https://github.com/LIS/LISAv2/blob/master/Documents/How-to-use.md).
