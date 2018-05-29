#!/bin/bash

#Required
JenkinsUser="microsoft"

#Required
UpstreamBuildNumber="unique-string"

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
GitUrlForAutomation=""

#Required
GitBranchForAutomation=""

#Required at least one test selection choise from following.
#TestByTestname="Azure>>VERIFY-DEPLOYMENT-PROVISION>>eastus2,Azure>>VERIFY-DEPLOYMENT-PROVISION>>eastus"
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

#Required
JenkinsURL="penguinator.westus2.cloudapp.azure.com"

#Required
#TestPipeline="/view/Microsoft/job/Microsoft/job/Microsoft-Test-Execution-Pipeline"
TestPipeline=""

#Required to upload Files to jenkins server using FTP
FtpUsername=""
FtpPassword=""

ExitCode=0

##############################################################
#Validate the parameters
##############################################################
if [[ $JenkinsUser == "" ]] || [[ -z $JenkinsUser ]];
then
    echo "JenkinsUser parameter is required"
    ExitCode=$(( ExitCode + 1 ))
fi
if [[ $UpstreamBuildNumber == "" ]] || [[ -z $UpstreamBuildNumber ]];
then
    echo "UpstreamBuildNumber parameter is required"
    ExitCode=$(( ExitCode + 1 ))
fi
if ([[ $ImageSource == "" ]] || [[ -z $ImageSource ]]) && ([[ $CustomVHD == "" ]] || [[ -z $CustomVHD ]]) && ([[ $CustomVHDURL == "" ]] || [[ -z $CustomVHDURL ]]);
then
    echo "ImageSource/CustomVHD/CustomVHDURL parameter is required"
    ExitCode=$(( ExitCode + 1 ))
else
    if ([[ ! $ImageSource == "" ]] || [[ ! -z $ImageSource ]]);
    then
        URLEncodedImageSource=${ImageSource// /%20}
        echo "ImageSource '${ImageSource}' encoded to '${URLEncodedImageSource}'"
    fi
fi
if [[ $Kernel == "" ]] || [[ -z $Kernel ]];
then

    echo "Kernel parameter is required"
    ExitCode=$(( ExitCode + 1 ))
fi
if [[ $Kernel == "" ]] || [[ -z $Kernel ]];
then

    echo "Kernel parameter is required"
    ExitCode=$(( ExitCode + 1 ))
fi
if [[ $GitBranchForAutomation == "" ]] || [[ -z $GitBranchForAutomation ]];
then
    echo "GitUrlForAutomation parameter is required"
    ExitCode=$(( ExitCode + 1 ))
fi
if ([[ $TestByTestname == "" ]] || [[ -z $TestByTestname ]]) && ([[ $TestByCategorisedTestname == "" ]] || [[ -z $TestByCategorisedTestname ]]) && ([[ $TestByCategory == "" ]] || [[ -z $TestByCategory ]]) && ([[ $TestByTag == "" ]] || [[ -z $TestByTag ]]);
then
    echo "TestByTestname/TestByCategorisedTestname/TestByCategory/TestByTag parameter is required"
    ExitCode=$(( ExitCode + 1 ))
else
    if [[ ! $TestByTestname == "" ]] || [[ ! -z $TestByTestname ]];
    then
        EncodedTestByTestname=${TestByTestname//>>/%3E%3E}
        echo "TestByTestname '${TestByTestname}' encoded to '${EncodedTestByTestname}'"
    fi
    if [[ ! $TestByCategorisedTestname == "" ]] || [[ ! -z $TestByCategorisedTestname ]];
    then
        EncodedTestByCategorisedTestname=${TestByCategorisedTestname//>>/%3E%3E}
        echo "TestByCategorisedTestname '${TestByCategorisedTestname}' encoded to '${EncodedTestByCategorisedTestname}'"
    fi
    if [[ ! $TestByCategory == "" ]] || [[ ! -z $TestByCategory ]];
    then
        EncodedTestByCategory=${TestByCategory//>>/%3E%3E}
        echo "TestByCategory '${TestByCategory}' encoded to '${EncodedTestEncodedTestByCategoryByTestname}'"
    fi
    if [[ ! $TestByTag == "" ]] || [[ ! -z $TestByTag ]];
    then
        EncodedTestByTag=${TestByTag//>>/%3E%3E}
        echo "TestByTag '${TestByTag}' encoded to '${EncodedTestByTag}'"
    fi
fi
if [[ $Email == "" ]] || [[ -z $Email ]];
then
    echo "GitUrlForAutomation parameter is required"
    ExitCode=$(( ExitCode + 1 ))
else
    EncodedEmail=${Email//@/%40}
    echo "Email '${Email}' encoded to '${EncodedEmail}'"    
fi
if [[ $ExitCode == 0 ]];
then
    echo "Parameters are valid."
else
    echo "Exiting with 1"
    exit 1
fi


#################################################
#Generate the Link

RemoteTriggerURL="https://${JenkinsUser}:${ApiToken}@${JenkinsURL}${TestPipeline}/buildWithParameters?token=1234567890&JenkinsUser=${JenkinsUser}&UpstreamBuildNumber=${UpstreamBuildNumber}"

#Add image source.
if ([[ ! $URLEncodedImageSource == "" ]] || [[ ! -z $URLEncodedImageSource ]]);
then
    RemoteTriggerURL="${RemoteTriggerURL}&ImageSource=${URLEncodedImageSource}"
elif ([[ ! $CustomVHD == "" ]] || [[ ! -z $CustomVHD ]]);
then
    RemoteTriggerURL="${RemoteTriggerURL}&CustomVHD=${CustomVHD}"
elif ([[ ! $CustomVHDURL == "" ]] || [[ ! -z $CustomVHDURL ]]);
then
    RemoteTriggerURL="${RemoteTriggerURL}&CustomVHDURL=${CustomVHDURL}"
fi

#Add Kernel and Git details
RemoteTriggerURL="${RemoteTriggerURL}&Kernel=${Kernel}&GitUrlForAutomation=${GitUrlForAutomation}&GitBranchForAutomation=${GitBranchForAutomation}"

#Add Tests
if ([[ ! $EncodedTestByTestname == "" ]] || [[ ! -z $EncodedTestByTestname ]]);
then
    RemoteTriggerURL="${RemoteTriggerURL}&TestByTestname=${EncodedTestByTestname}"
fi
if ([[ ! $EncodedTestByCategorisedTestname == "" ]] || [[ ! -z $EncodedTestByCategorisedTestname ]]);
then
    RemoteTriggerURL="${RemoteTriggerURL}&TestByCategorisedTestname=${EncodedTestByCategorisedTestname}"
fi
if ([[ ! $EncodedTestByCategory == "" ]] || [[ ! -z $EncodedTestByCategory ]]);
then
    RemoteTriggerURL="${RemoteTriggerURL}&TestByCategory=${EncodedTestByCategory}"
fi
if ([[ ! $EncodedTestByTag == "" ]] || [[ ! -z $EncodedTestByTag ]]);
then
    RemoteTriggerURL="${RemoteTriggerURL}&TestByTag=${EncodedTestByTag}"
fi
#Add email
RemoteTriggerURL="${RemoteTriggerURL}&Email=${EncodedEmail}"
RemoteQueryURL="https://${JenkinsUser}:${ApiToken}@${JenkinsURL}${TestPipeline}/lastBuild/api/xml"
echo ${RemoteTriggerURL}
echo "Triggering job..."
curl -v -X POST ${RemoteTriggerURL}
if [[ "$?" == "0" ]];
then
    xmlResponse=$(curl -v -X GET "${RemoteQueryURL}")
    echo $xmlResponse | tr ">" "\n" | grep penguinator | tr "<" "\n" | head -1
    echo "Job triggered successfully."
else
    echo "Failed to trigger job."
fi