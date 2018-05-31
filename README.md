# Test Automation for Microsoft Linux on Azure & Hyper-V

Automation platform for Linux images testing on Microsoft Azure and Hyper-V

## Overview

LISAv2 (Linux Integrated Service Automation) is the One-stop automation solution for Linux images/kernel testing on Microsoft Azure and Hyper-V. LISA-v2 supports both Microsoft Azure and Hyper-V automation, and they use PowerShell, BASH and python scripts. Tests for feature, performance, stress and regression about new Linux Operating Systems and kernels. The test suite provides Build Verification Tests (BVTs), Azure VNET Tests and Network tests.

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
2. Start Web Platform Installer and select Azure PowerShell and proceed for Azure PowerShell Installation.

### Authenticate Your Machine with Your Azure Subscription

There are two ways to authenticate your machine with your subscription.

1. Azure AD method

      This creates a 12 Hours temporary session in PowerShell, in that session, you are allowed to run Windows Azure Cmdlets to control / use your subscription. After 12 hours you will be asked to enter username and password of your subscription. This may create problems long running automations, hence we use certificate method.

2. Certificate Method.

      To learn more about how to configure your PowerShell with your subscription, please visit [here](http://azure.microsoft.com/en-us/documentation/articles/powershell-install-configure/#Connect).

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

2. Save file.

### Prepare VHD to work in Azure

`Applicable if you are uploading your own VHD with Linux OS to Azure.`

A VHD with Linux OS must be made compatible to work in Azure environment. This includes �

        1. Installation of Linux Integration Services to Linux VM (if already not present)
        2. Installation of Windows Azure Linux Agent to Linux VM (if already not installed.)
        3. Installation of minimum required packages. (Applicable if you want to run Tests using Automation code)

Please follow the steps mentioned at [here](https://docs.microsoft.com/en-us/azure/virtual-machines/linux/create-upload-generic)

### Prepare VHD to work with Automation code

`Applicable if you are using already uploaded VHD / Platform Image to run automation.`

To run automation code successfully, you need have following packages installed in your Linux VHD.

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

### Create SSH Key Pair

`PublicKey.cer � PrivateKey.ppk`

A Linux Virtual machine login can be done with Password authentication or SSH key pair authentication. You must create a Public Key and Private key to run automation successfully. To learn more about how to create SSH key pair, please visit [here](http://azure.microsoft.com/en-us/documentation/articles/virtual-machines-linux-use-ssh-key/).

After creating Public Key (.cer) and putty compatible private key (.ppk), you must put it in your `automation_root_folder\ssh\` folder and mention their names in Azure XML file.

### VNET Preparation

`Required for executing Virtual Network Tests`

#### Create a Virtual Network in Azure

A virtual network should be created and connected to Customer Network before running VNET test cases. To learn about how to create a virtual network on Azure, please visit [here](https://docs.microsoft.com/en-us/azure/vpn-gateway/vpn-gateway-howto-site-to-site-resource-manager-portal).

#### Create A customer site using RRAS

Apart from Virtual Network in Azure, you also need a network (composed of Subnets and DNS server) to work as Customer Network. If you don�t have separate network to run VNET, you can create a virtual customer network using RRAS. To learn more, please visit [here](https://social.msdn.microsoft.com/Forums/en-US/b7d15a76-37b3-4307-98e3-d9efef5767b8/azure-site-to-site-vpn-routing?forum=WAVirtualMachinesVirtualNetwork).

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

        .\AzureAutomationManager.ps1 -xmlConfigFile .\Azure_ICA_ALL.xml -runtests -email �Distro <DistroName> -cycleName <TestCycleToExecute> -UseAzureResourceManager

#### More Information

For more details, please refer to the documents [here](https://github.com/LIS/LISAv2/tree/master/Documentation/How-to-use.md).
