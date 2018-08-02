#!/bin/bash
##############################################################################################
# LaunchTestPipelineRemotely.sh
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#<#
#.SYNOPSIS
#   <Description>

#.PARAMETER
#   <Parameters>

#.INPUTS


#.NOTES
#    Creation Date:  
#    Purpose/Change: 

#.EXAMPLE
# Method 1: You can pass all the parameters from a parameters file.
#./LaunchTestPipelineRemotely.sh -ParametersFile <Path to parameters file>
# Method 2: You can also pass all the perameters to commandline.
#./LaunchTestPipelineRemotely.sh -JenkinsUser "assigned username" -UpstreamBuildNumber 
#                                   <UniqueBuildID> ... etc.

#>
###############################################################################################

while echo $1 | grep ^- > /dev/null; do
	eval $( echo $1 | sed 's/-//g' | tr -d '\012')=$2
	shift
	shift
done

LogMsg()
{
	echo "[$(date +"%x %r %Z")] ${1}"
	echo "[$(date +"%x %r %Z")] ${1}" >> "LaunchTestPipelineRemotely.log"
}

#Define static variables
JenkinsURL="penguinator.westus2.cloudapp.azure.com"

#Verify the parameters file and import parameters.
if [[ ! -z $ParametersFile ]]; then
	LogMsg "Parameters File: $ParametersFile"
	if [[ -f $ParametersFile  ]]; then
		LogMsg "Importing parameters..."
		source $ParametersFile
	else
		LogMsg "Unable to locate $ParametersFile. Exiting with 1"
		exit 1
	fi
fi

ExitCode=0

##############################################################
#Validate the parameters
##############################################################
if [[ $JenkinsUser == "" ]] || [[ -z $JenkinsUser ]]; then
	LogMsg "JenkinsUser parameter is required"
	ExitCode=$(( ExitCode + 1 ))
fi

if [[ $UpstreamBuildNumber == "" ]] || [[ -z $UpstreamBuildNumber ]]; then
	UpstreamBuildNumber=$(cat /dev/urandom | tr -dc '0-9' | fold -w 10 | head -1)
	LogMsg "UpstreamBuildNumber was not given. Using random build ID: ${UpstreamBuildNumber}"
fi

if ([[ $ImageSource == "" ]] || [[ -z $ImageSource ]]) && ([[ $CustomVHD == "" ]] || [[ -z $CustomVHD ]]) && ([[ $CustomVHDURL == "" ]] || [[ -z $CustomVHDURL ]]); then
	LogMsg "ImageSource/CustomVHD/CustomVHDURL parameter is required"
	ExitCode=$(( ExitCode + 1 ))
else
	if ([[ ! $ImageSource == "" ]] || [[ ! -z $ImageSource ]]); then
		URLEncodedImageSource=${ImageSource// /%20}
		#echo "ImageSource '${ImageSource}' encoded to '${URLEncodedImageSource}'"
	fi

	if ([[ ! $CustomVHD == "" ]] || [[ ! -z $CustomVHD ]]); then
		VHDName=$(basename $CustomVHD)
		if ([[ -f $CustomVHD ]]); then
			LogMsg "Local file ${CustomVHD} available. It will be uploaded."
		else
			LogMsg "No local file ${CustomVHD}. Assume it exists in ftp server."
		fi
	fi
fi

if [[ $Kernel == "" ]] || [[ -z $Kernel ]]; then
	LogMsg "Kernel parameter is required."
	ExitCode=$(( ExitCode + 1 ))
else
	if [[ $Kernel == "custom" ]]; then
		if [[ ! $CustomKernelFile == "" ]] || [[ ! -z $CustomKernelFile ]]; then
			KernelName=$(basename $CustomKernelFile)
			if ([[ -f $CustomKernelFile ]]); then
				LogMsg "Local file ${CustomKernelFile} available. It will be uploaded."
			else
				LogMsg "No local file ${CustomKernelFile}. Assume it exists in ftp server."
			fi            
		fi
	fi
fi

if [[ $GitUrlForAutomation == "" ]] || [[ -z $GitUrlForAutomation ]]; then
	LogMsg "GitUrlForAutomation parameter is required"
	ExitCode=$(( ExitCode + 1 ))
fi

if [[ $GitBranchForAutomation == "" ]] || [[ -z $GitBranchForAutomation ]]; then
	LogMsg "GitBranchForAutomation parameter is required"
	ExitCode=$(( ExitCode + 1 ))
fi

if ([[ $TestByTestname == "" ]] || [[ -z $TestByTestname ]]) && ([[ $TestByCategorisedTestname == "" ]] || [[ -z $TestByCategorisedTestname ]]) && ([[ $TestByCategory == "" ]] || [[ -z $TestByCategory ]]) && ([[ $TestByTag == "" ]] || [[ -z $TestByTag ]]); then
	LogMsg "TestByTestname/TestByCategorisedTestname/TestByCategory/TestByTag parameter is required"
	ExitCode=$(( ExitCode + 1 ))
else
	if [[ ! $TestByTestname == "" ]] || [[ ! -z $TestByTestname ]];	then
		EncodedTestByTestname=${TestByTestname//>>/%3E%3E}
		#echo "TestByTestname '${TestByTestname}' encoded to '${EncodedTestByTestname}'"
	fi

	if [[ ! $TestByCategorisedTestname == "" ]] || [[ ! -z $TestByCategorisedTestname ]]; then
		EncodedTestByCategorisedTestname=${TestByCategorisedTestname//>>/%3E%3E}
		#echo "TestByCategorisedTestname '${TestByCategorisedTestname}' encoded to '${EncodedTestByCategorisedTestname}'"
	fi

	if [[ ! $TestByCategory == "" ]] || [[ ! -z $TestByCategory ]];	then
		EncodedTestByCategory=${TestByCategory//>>/%3E%3E}
		#echo "TestByCategory '${TestByCategory}' encoded to '${EncodedTestEncodedTestByCategoryByTestname}'"
	fi

	if [[ ! $TestByTag == "" ]] || [[ ! -z $TestByTag ]]; then
		EncodedTestByTag=${TestByTag//>>/%3E%3E}
		#echo "TestByTag '${TestByTag}' encoded to '${EncodedTestByTag}'"
	fi
fi

if [[ $Email == "" ]] || [[ -z $Email ]]; then
	LogMsg "Email parameter is required"
	ExitCode=$(( ExitCode + 1 ))
else
	EncodedEmail=${Email//@/%40}
	#echo "Email '${Email}' encoded to '${EncodedEmail}'"    
fi

if [[ $ExitCode == 0 ]]; then
	LogMsg "Parameters are valid."
else
	LogMsg "Exiting with 1"
	exit 1
fi

#################################################
#Generate the Link

RemoteTriggerURL="https://${JenkinsUser}:${ApiToken}@${JenkinsURL}/job/${TestPipeline}/buildWithParameters?token=1234567890&JenkinsUser=${JenkinsUser}&UpstreamBuildNumber=${UpstreamBuildNumber}"

#Add image source.
if ([[ ! $URLEncodedImageSource == "" ]] || [[ ! -z $URLEncodedImageSource ]]); then
	RemoteTriggerURL="${RemoteTriggerURL}&ImageSource=${URLEncodedImageSource}"
elif ([[ ! $CustomVHD == "" ]] || [[ ! -z $CustomVHD ]]); then
	if ([[ -f $CustomVHD ]]); 	then
		LogMsg "Uploading ${CustomVHD}..."
		curl -T $CustomVHD ftp://${JenkinsURL} --user ${FtpUsername}:${FtpPassword}
	fi
	RemoteTriggerURL="${RemoteTriggerURL}&CustomVHD=${VHDName}"
elif ([[ ! $CustomVHDURL == "" ]] || [[ ! -z $CustomVHDURL ]]); then
	RemoteTriggerURL="${RemoteTriggerURL}&CustomVHDURL=${CustomVHDURL}"
fi

#Add Kernel and Git details
RemoteTriggerURL="${RemoteTriggerURL}&Kernel=${Kernel}"
if [[ $Kernel == 'custom' ]]; then
	if ([[ ! $CustomKernelFile == "" ]] || [[ ! -z $CustomKernelFile ]]); then
		if [[ -f $CustomKernelFile ]]; then
			LogMsg "Uploading ${KernelName}..."
			curl -T $KernelName ftp://${JenkinsURL} --user ${FtpUsername}:${FtpPassword}
		fi
		RemoteTriggerURL="${RemoteTriggerURL}&CustomKernelFile=${KernelName}"
	elif ([[ ! $CustomKernelURL == "" ]] || [[ ! -z $CustomKernelURL ]]); then
		RemoteTriggerURL="${RemoteTriggerURL}&CustomKernelURL=${CustomKernelURL}" 
	fi    
fi
RemoteTriggerURL="${RemoteTriggerURL}&GitUrlForAutomation=${GitUrlForAutomation}&GitBranchForAutomation=${GitBranchForAutomation}"

#Add Tests
if ([[ ! $EncodedTestByTestname == "" ]] || [[ ! -z $EncodedTestByTestname ]]); then
    RemoteTriggerURL="${RemoteTriggerURL}&TestByTestname=${EncodedTestByTestname}"
fi

if ([[ ! $EncodedTestByCategorisedTestname == "" ]] || [[ ! -z $EncodedTestByCategorisedTestname ]]); then
    RemoteTriggerURL="${RemoteTriggerURL}&TestByCategorisedTestname=${EncodedTestByCategorisedTestname}"
fi

if ([[ ! $EncodedTestByCategory == "" ]] || [[ ! -z $EncodedTestByCategory ]]); then
    RemoteTriggerURL="${RemoteTriggerURL}&TestByCategory=${EncodedTestByCategory}"
fi

if ([[ ! $EncodedTestByTag == "" ]] || [[ ! -z $EncodedTestByTag ]]); then
    RemoteTriggerURL="${RemoteTriggerURL}&TestByTag=${EncodedTestByTag}"
fi
#Add email
RemoteTriggerURL="${RemoteTriggerURL}&Email=${EncodedEmail}"
RemoteQueryURL="https://${JenkinsUser}:${ApiToken}@${JenkinsURL}/job/${TestPipeline}/lastBuild/api/xml"
#echo ${RemoteTriggerURL}

if [[ "$ExitCode" == "0" ]]; then
	LogMsg "Triggering job..."
	curl --silent -X POST ${RemoteTriggerURL}
	if [[ "$?" == "0" ]]; then
		LogMsg "Job triggered successfully."
		if [[ ! -f ./jq ]]; then
			LogMsg "Copying json parser from Tools folder"
			cp ../Tools/jq .
			chmod +x jq
		fi
		BuildNumber=$(curl --silent -X GET "https://${JenkinsUser}:${ApiToken}@${JenkinsURL}/job/${TestPipeline}/lastBuild/api/json" | ./jq '.id' | sed 's/"//g')
		BuildURL=$(curl --silent -X GET "https://${JenkinsUser}:${ApiToken}@${JenkinsURL}/job/${TestPipeline}/${BuildNumber}/api/json" | ./jq '.url' | sed 's/"//g')
		BuildState=$(curl --silent -X GET "https://${JenkinsUser}:${ApiToken}@${JenkinsURL}/job/${TestPipeline}/${BuildNumber}/api/json" | ./jq '.building' | sed 's/"//g')
		BuildResult=$(curl --silent -X GET "https://${JenkinsUser}:${ApiToken}@${JenkinsURL}/job/${TestPipeline}/${BuildNumber}/api/json" | ./jq '.result' | sed 's/"//g')
		BlueOceanURL="https://${JenkinsURL}/blue/organizations/jenkins/${TestPipeline}/detail/${TestPipeline}/${BuildNumber}/pipeline"

		LogMsg "--------------------------------------"
		LogMsg "BuildURL (BlueOcean) : ${BlueOceanURL}"
		LogMsg "--------------------------------------"
		LogMsg "BuildURL (Classic) : ${BuildURL}console"
		LogMsg "--------------------------------------"

		if [[ $WaitForResult == "yes" ]]; then
			while [[ "$BuildState" ==  "true" ]]
			do
				BuildState=$(curl --silent -X GET "https://${JenkinsUser}:${ApiToken}@${JenkinsURL}/job/${TestPipeline}/${BuildNumber}/api/json" | ./jq '.building' | sed 's/"//g')
				LogMsg "Current state : Running."
				sleep 5       
			done
			BuildResult=$(curl --silent -X GET "https://${JenkinsUser}:${ApiToken}@${JenkinsURL}/job/${TestPipeline}/${BuildNumber}/api/json" | ./jq '.result' | sed 's/"//g')
			if [[ "$BuildResult" == "SUCCESS" ]]; then
				LogMsg "Current State : Completed."
				LogMsg "Result: SUCCESS."
				exit 0
			else
				LogMsg "Result: ${BuildResult}"
				exit 1
			fi
		else
			exit 0
		fi
	else
		LogMsg "Failed to trigger job."
		exit 1
	fi
else
	LogMsg "Found ${ExitCode} errors. Exiting without launching tests."
	exit 1
fi
