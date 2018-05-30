#!/bin/bash

##################################################
#Paramerers file for LaunchTestPipelineRemotely.sh
##################################################

#Required
JenkinsUser=""

#Required
UpstreamBuildNumber=""

#Required any one of the following
ImageSource=""
CustomVHD=""
CustomVHDURL=""

#Required
Kernel="default"

#Required any of the following if Kernel=custom
CustomKernelFile=""
CustomKernelURL=""

#Required
GitUrlForAutomation="https://github.com/LIS/LISAv2.git"

#Required
GitBranchForAutomation="master"

#Required at least one test selection choise from following.
TestByTestname=""
TestByCategorisedTestname=""
TestByCategory=""
TestByTag=""

#Required
Email=""

#Optional
LinuxUsername=""
LinuxPassword=""

#Required to access Jenkins.
ApiToken=""
#Required to upload Files to jenkins server using FTP
FtpUsername=""
FtpPassword=""

#Required
JenkinsURL="penguinator.westus2.cloudapp.azure.com"

#Required
#TestPipeline="/view/Microsoft/job/Microsoft/job/Microsoft-Test-Execution-Pipeline"
TestPipeline=""