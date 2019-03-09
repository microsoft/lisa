#!/bin/bash
##############################################################################################
# TestParameters.sh
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#<#
#.SYNOPSIS
#   Paramerers file for LaunchTestPipelineRemotely.sh

#.PARAMETER
#   <Parameters>

#.INPUTS


#.NOTES
#    Creation Date:  
#    Purpose/Change: 

#.EXAMPLE


#>
###############################################################################################

#

#Required (Your jenkins username)
#This will be used to login jenkins in conjuction with ApiToken
JenkinsUser=""


#Required (You can generate your access token in the jenkins.)
ApiToken=""


#Required only if you are uploading files from your local machine to Jenkins. These credentials are different from Jenkins username/password. 
FtpUsername=""
FtpPassword=""


#Required (Image / VHD under test)
#Provide ONLY ONE of the following.
ImageSource=""
#Example ImageSource="Publisher Offer Sku Version"
CustomVHD=""
#Example CustomVHD="/path/to/local/vhd/vhdx/vhd.xz file"
CustomVHDURL=""
#Example CustomVHDURL="http://downloadable/link/to/your/file.vhd/vhdx/vhd.xz"


#Required (This kernel be installed before starting test)
Kernel=""
#Example Kernel="default/custom/linuxnext"


#Required ONLY IF you set Kernel=custom
CustomKernelFile=""
#Example CustomKernelFile="/path/to/local/kernel/file.rpm/file.deb"
CustomKernelURL=""
#Example CustomKernelURL="http://downloadable/link/to/your/kernel.rpm/kernel.deb"


#Required (Source code for tests)
GitUrlForAutomation="https://github.com/LIS/LISAv2.git"
#Required
GitBranchForAutomation="master"


#Required AT LEAST ONE test selection choise from following.
#Multiple tests can be submitted using comma separated values
TestByTestname=""
#Example TestByTestname="Azure>>VERIFY-DEPLOYMENT-PROVISION>>eastasia,Azure>>VERIFY-HOSTNAME>>westeurope"
TestByCategorisedTestname=""
#Example TestByCategorisedTestname="Azure>>Smoke>>default>>VERIFY-DEPLOYMENT-PROVISION>>northeurope,Azure>>Functional>>SRIOV>>VERIFY-SRIOV-LSPCI>>southcentralus"
TestByCategory=""
#Example TestByCategory="Azure>>Functional>>SRIOV>>eastus,Azure>>Community>>LTP>>westeurope"
TestByTag=""
#Example TestByTag="Azure>>boot>>northcentralus,Azure>>wala>>westeurope,Azure>>gpu>>eastus"


#Required (Email will be sent to these email addresses. Comma separated email IDs are accepted.
Email=""


#Required (These credential be used to create your test VMs. In case of debugging, you can use this to login to test VM.)
LinuxUsername=""
LinuxPassword=""


#Required (Your pipeline name)
TestPipeline=""
#Example TestPipeline="<PatnerName>-Test-Execution-Pipeline"

#Optional. (Keep the polling enabled after build job is triggered and exit with final result.)
WaitForResult=""
#Example WaitForResul="yes"