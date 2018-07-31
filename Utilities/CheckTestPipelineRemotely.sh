#!/bin/bash
##############################################################################################
# CheckTestPipelineRemotely.sh
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#<#
#.SYNOPSIS
#    Pipeline framework modules.

#.PARAMETER
#	<Parameters>

#.INPUTS


#.NOTES
#    Creation Date:  
#    Purpose/Change: 

#.EXAMPLE
#    ./CheckTestPipelineRemotely.sh -BuildNumber <JenkinsBuildID>

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
	echo "[$(date +"%x %r %Z")] ${1}" >> "CheckTestPipelineRemotely.log"
}

#Define static variables
JenkinsURL="penguinator.westus2.cloudapp.azure.com"

#Verify the parameters file and import parameters.
if [[ ! -z $ParametersFile ]]; then
	LogMsg "Parameters File: $ParametersFile"
	if [[ -f $ParametersFile  ]]; 	then
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
if [[ $BuildNumber == "" ]] || [[ -z $BuildNumber ]]; then
	LogMsg "BuildNumber parameter is required"
	ExitCode=$(( ExitCode + 1 ))
fi

if [[ $ExitCode == 0 ]]; then
	LogMsg "Parameters are valid."
else
	LogMsg "Exiting with 1"
	exit 1
fi

if [[ ! -f ./jq ]]; then
	LogMsg "Copying json parser from Tools folder"
	cp ../Tools/jq .
	chmod +x jq
fi

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
	if [[ "$BuildState" == "true" ]]; then
		LogMsg "BuildState : Running"
	else
		LogMsg "BuildState : Completed"
	fi
	LogMsg "BuildResult : ${BuildResult}"
	exit 0
fi
