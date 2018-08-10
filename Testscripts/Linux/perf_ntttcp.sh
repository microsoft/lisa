#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# perf_ntttcp.sh
# Description:
#    Download and run ntttcp network performance tests.
#    This script needs to be run on client VM.
#
# Supported Distros:
#    Ubuntu 16.04
#######################################################################

CONSTANTS_FILE="./constants.sh"
UTIL_FILE="./utils.sh"
ICA_TESTRUNNING="TestRunning"           # The test is running
ICA_TESTCOMPLETED="TestCompleted"       # The test completed successfully
ICA_TESTABORTED="TestAborted"           # Error during the setup of the test
ICA_TESTFAILED="TestFailed"                     # Error occurred during the test
touch ./ntttcpTest.log

LogMsg()
{
	echo `date "+%b %d %Y %T"` : "${1}"	# Add the time stamp to the log message
	echo "${1}" >> ./ntttcpTest.log
}

UpdateTestState()
{
	echo "${1}" > ./state.txt
}

. ${CONSTANTS_FILE} || {
	errMsg="Error: missing ${CONSTANTS_FILE} file"
	LogMsg "${errMsg}"
	UpdateTestState $ICA_TESTABORTED
	exit 10
}
. ${UTIL_FILE} || {
	errMsg="Error: missing ${UTIL_FILE} file"
	LogMsg "${errMsg}"
	UpdateTestState $ICA_TESTABORTED
	exit 10
}

if [ ! ${server} ]; then
	errMsg="Please add/provide value for server in constants.sh. server=<server ip>"
	LogMsg "${errMsg}"
	echo "${errMsg}" >> ./summary.log
	UpdateTestState $ICA_TESTABORTED
	exit 1
fi
if [ ! ${client} ]; then
	errMsg="Please add/provide value for client in constants.sh. client=<client ip>"
	LogMsg "${errMsg}"
	echo "${errMsg}" >> ./summary.log
	UpdateTestState $ICA_TESTABORTED
	exit 1
fi

if [ ! ${testDuration} ]; then
	errMsg="Please add/provide value for testDuration in constants.sh. testDuration=60"
	LogMsg "${errMsg}"
	echo "${errMsg}" >> ./summary.log
	UpdateTestState $ICA_TESTABORTED
	exit 1
fi

if [ ! ${nicName} ]; then
	errMsg="Please add/provide value for nicName in constants.sh. nicName=eth0/bond0"
	LogMsg "${errMsg}"
	echo "${errMsg}" >> ./summary.log
	UpdateTestState $ICA_TESTABORTED
	exit 1
fi
#Make & build ntttcp on client and server Machine

LogMsg "Configuring client ${client}..."
ssh ${client} ". $UTIL_FILE && install_ntttcp"
ssh ${client} "which ntttcp"
if [ $? -ne 0 ]; then
	LogMsg "Error: ntttcp installation failed in ${client}.."
	UpdateTestState "TestAborted"
	exit 1
fi

LogMsg "Configuring server ${server}..."
ssh ${server} ". $UTIL_FILE && install_ntttcp"
ssh ${server} "which ntttcp"
if [ $? -ne 0 ]; then
	LogMsg "Error: ntttcp installation failed in ${server}.."
	UpdateTestState "TestAborted"
	exit 1
fi

#Now, start the ntttcp client on client VM.
ssh root@${client} "chmod +x run-ntttcp-and-tcping.sh report-ntttcp-and-tcping.sh"

LogMsg "Now running NTTTCP test"
ssh root@${client} "rm -rf ntttcp-test-logs"
ssh root@${client} "./run-ntttcp-and-tcping.sh ntttcp-test-logs ${server} root ${testDuration} ${nicName} '$testConnections'"
ssh root@${client} "./report-ntttcp-and-tcping.sh ntttcp-test-logs '$testConnections'"
ssh root@${client} "cp ntttcp-test-logs/* ."

UpdateTestState ICA_TESTCOMPLETED