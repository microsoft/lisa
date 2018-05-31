##############################################################################################
# TriggerTestPipelineRemotely.sh
# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.
# Description : 
# Operations :
#              
## Author : lisasupport@microsoft.com
###############################################################################################

#!/bin/bash

#####################################################################################################
#How to use:

# Method 1: You can pass all the parameters from a parameters file.
#./LaunchTestPipelineRemotely.sh -ParametersFile <Path to parameters file>

# Method 2: You can also pass all the perameters to commandline.
#./LaunchTestPipelineRemotely.sh -JenkinsUser "assigned username" -UpstreamBuildNumber <UniqueBuildID> ... etc.

######################################################################################################

while echo $1 | grep ^- > /dev/null; do
    eval $( echo $1 | sed 's/-//g' | tr -d '\012')=$2
    shift
    shift
done

#Define static variables
JenkinsURL="penguinator.westus2.cloudapp.azure.com"

#Verify the parameters file and import parameters.
if [[ ! -z $ParametersFile ]];
then
	echo "Parameters File: $ParametersFile"
	if [[ -f $ParametersFile  ]];
	then
		echo "Importing parameters..."
		source $ParametersFile
	else
		echo "Unable to locate $ParametersFile. Exiting with 1"
		exit 1
	fi
fi

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
    UpstreamBuildNumber=$(cat /dev/urandom | tr -dc '0-9' | fold -w 10 | head -1)
    echo "UpstreamBuildNumber was not given. Using random build ID: ${UpstreamBuildNumber}"
fi
if ([[ $ImageSource == "" ]] || [[ -z $ImageSource ]]) && ([[ $CustomVHD == "" ]] || [[ -z $CustomVHD ]]) && ([[ $CustomVHDURL == "" ]] || [[ -z $CustomVHDURL ]]);
then
    echo "ImageSource/CustomVHD/CustomVHDURL parameter is required"
    ExitCode=$(( ExitCode + 1 ))
else
    if ([[ ! $ImageSource == "" ]] || [[ ! -z $ImageSource ]]);
    then
        URLEncodedImageSource=${ImageSource// /%20}
        #echo "ImageSource '${ImageSource}' encoded to '${URLEncodedImageSource}'"
    fi
    if ([[ ! $CustomVHD == "" ]] || [[ ! -z $CustomVHD ]]);
    then
        if ([[ -f $CustomVHD ]]);
        then
            VHDName=$(basename $CustomVHD)
            EncodedVHDName="${UpstreamBuildNumber}-${VHDName}"
            #echo "CustomVHD '${VHDName}' encoded to '${EncodedVHDName}'"
        else
            echo "CustomVHD '${CustomVHD}' does not exists. Please verify path."
        fi
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
if [[ $GitUrlForAutomation == "" ]] || [[ -z $GitUrlForAutomation ]];
then
    echo "GitUrlForAutomation parameter is required"
    ExitCode=$(( ExitCode + 1 ))
fi
if [[ $GitBranchForAutomation == "" ]] || [[ -z $GitBranchForAutomation ]];
then
    echo "GitBranchForAutomation parameter is required"
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
        #echo "TestByTestname '${TestByTestname}' encoded to '${EncodedTestByTestname}'"
    fi
    if [[ ! $TestByCategorisedTestname == "" ]] || [[ ! -z $TestByCategorisedTestname ]];
    then
        EncodedTestByCategorisedTestname=${TestByCategorisedTestname//>>/%3E%3E}
        #echo "TestByCategorisedTestname '${TestByCategorisedTestname}' encoded to '${EncodedTestByCategorisedTestname}'"
    fi
    if [[ ! $TestByCategory == "" ]] || [[ ! -z $TestByCategory ]];
    then
        EncodedTestByCategory=${TestByCategory//>>/%3E%3E}
        #echo "TestByCategory '${TestByCategory}' encoded to '${EncodedTestEncodedTestByCategoryByTestname}'"
    fi
    if [[ ! $TestByTag == "" ]] || [[ ! -z $TestByTag ]];
    then
        EncodedTestByTag=${TestByTag//>>/%3E%3E}
        #echo "TestByTag '${TestByTag}' encoded to '${EncodedTestByTag}'"
    fi
fi
if [[ $Email == "" ]] || [[ -z $Email ]];
then
    echo "Email parameter is required"
    ExitCode=$(( ExitCode + 1 ))
else
    EncodedEmail=${Email//@/%40}
    #echo "Email '${Email}' encoded to '${EncodedEmail}'"    
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

RemoteTriggerURL="https://${JenkinsUser}:${ApiToken}@${JenkinsURL}/job/${TestPipeline}/buildWithParameters?token=1234567890&JenkinsUser=${JenkinsUser}&UpstreamBuildNumber=${UpstreamBuildNumber}"

#Add image source.
if ([[ ! $URLEncodedImageSource == "" ]] || [[ ! -z $URLEncodedImageSource ]]);
then
    RemoteTriggerURL="${RemoteTriggerURL}&ImageSource=${URLEncodedImageSource}"
elif ([[ ! $CustomVHD == "" ]] || [[ ! -z $CustomVHD ]]);
then
    echo "Uploading ${CustomVHD} with name ${EncodedVHDName}..."
    curl -T $CustomVHD ftp://${JenkinsURL} --user ${FtpUsername}:${FtpPassword} -Q "-RNFR ${VHDName}" -Q "-RNTO ${EncodedVHDName}"
    RemoteTriggerURL="${RemoteTriggerURL}&CustomVHD=${VHDName}"
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
RemoteQueryURL="https://${JenkinsUser}:${ApiToken}@${JenkinsURL}/job/${TestPipeline}/lastBuild/api/xml"
#echo ${RemoteTriggerURL}
echo "Triggering job..."
curl --silent -X POST ${RemoteTriggerURL}
if [[ "$?" == "0" ]];
then
    echo "Job triggered successfully."
    if [[ ! -f ./jq ]];
    then
        echo "Downloading json parser"
        curl --silent -O https://raw.githubusercontent.com/LIS/LISAv2/master/Tools/jq
        chmod +x jq
    fi
    BuildNumber=$(curl --silent -X GET "https://${JenkinsUser}:${ApiToken}@${JenkinsURL}/job/${TestPipeline}/lastBuild/api/json" | ./jq '.id' | sed 's/"//g')
    BuildURL=$(curl --silent -X GET "https://${JenkinsUser}:${ApiToken}@${JenkinsURL}/job/${TestPipeline}/${BuildNumber}/api/json" | ./jq '.url' | sed 's/"//g')
    BuildState=$(curl --silent -X GET "https://${JenkinsUser}:${ApiToken}@${JenkinsURL}/job/${TestPipeline}/${BuildNumber}/api/json" | ./jq '.building' | sed 's/"//g')
    BuildResult=$(curl --silent -X GET "https://${JenkinsUser}:${ApiToken}@${JenkinsURL}/job/${TestPipeline}/${BuildNumber}/api/json" | ./jq '.result' | sed 's/"//g')
    BlueOceanURL="https://${JenkinsURL}/blue/organizations/jenkins/${TestPipeline}/detail/${TestPipeline}/${BuildNumber}/pipeline"
    echo "--------------------------------------"
    echo "BuildURL (BlueOcean) : ${BlueOceanURL}"
    echo "--------------------------------------"
    echo "BuildURL (Classic) : ${BuildURL}console"
    echo "--------------------------------------"

    if [[ $WaitForResult == "yes" ]];
    then
        while [[ "$BuildState" ==  "true" ]]
        do
            BuildState=$(curl --silent -X GET "https://${JenkinsUser}:${ApiToken}@${JenkinsURL}/job/${TestPipeline}/${BuildNumber}/api/json" | ./jq '.building' | sed 's/"//g')
            echo "Current state : Running."
            sleep 5       
        done
        BuildResult=$(curl --silent -X GET "https://${JenkinsUser}:${ApiToken}@${JenkinsURL}/job/${TestPipeline}/${BuildNumber}/api/json" | ./jq '.result' | sed 's/"//g')
        if [[ "$BuildResult" == "SUCCESS" ]];
        then
            echo "Current State : Completed."
            echo "Result: SUCCESS."
            exit 0
        else
            echo "Result: ${BuildResult}"
            exit 1
        fi
    else
        exit 0
    fi
else
    echo "Failed to trigger job."
    exit 1
fi
