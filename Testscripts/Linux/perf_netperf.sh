#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# perf_netperf.sh
# Description:
#    Download and run netperf network performance tests.
#    This script needs to be run on client VM.
#
#######################################################################

CONSTANTS_FILE="./constants.sh"
UTIL_FILE="./utils.sh"
ICA_TESTRUNNING="TestRunning"           # The test is running
ICA_TESTCOMPLETED="TestCompleted"       # The test completed successfully
ICA_TESTABORTED="TestAborted"           # Error during the setup of the test
ICA_TESTFAILED="TestFailed"                     # Error occurred during the test
touch ./TestExecution.log

LogMsg()
{
    echo `date "+%b %d %Y %T"` : "${1}"	# Add the time stamp to the log message
    echo "${1}" >> ./TestExecution.log
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

if [ ! ${test_duration} ]; then
    errMsg="Please add/provide value for test_duration in constants.sh. test_duration=60"
    LogMsg "${errMsg}"
    echo "${errMsg}" >> ./summary.log
    UpdateTestState $ICA_TESTABORTED
    exit 1
fi

if [ ! ${test_type} ]; then
    errMsg="Please add/provide value for test_type in constants.sh. test_type=singlepps/maxpps"
    LogMsg "${errMsg}"
    echo "${errMsg}" >> ./summary.log
    UpdateTestState $ICA_TESTABORTED
    exit 1
fi
#Make & build netperf on client and server Machine
scp *.sh ${server}:

LogMsg "Configuring client ${client}..."
ssh ${client} ". $UTIL_FILE && install_netperf"
if [ $? -ne 0 ]; then
    LogMsg "Error: netperf installation failed in ${client}.."
    UpdateTestState $ICA_TESTABORTED
    exit 1
fi

LogMsg "Configuring server ${server}..."
ssh ${server} ". $UTIL_FILE && install_netperf"
if [ $? -ne 0 ]; then
    LogMsg "Error: netperf installation failed in ${server}.."
    UpdateTestState $ICA_TESTABORTED
    exit 1
fi

if [[ $(detect_linux_distribution) == coreos ]]; then
    netperf_cmd="docker run --network host lisms/netperf"
    sar_cmd="docker run --network host lisms/toolbox sar"
    ssh root@${server} ". $UTIL_FILE && Delete_Containers"
    ssh root@${client} ". $UTIL_FILE && Delete_Containers"
else
    netperf_cmd=""
    sar_cmd="sar"
fi

Kill_Process ${server} netserver
Kill_Process ${client} netperf

if [[ "$test_type" == "singlepps" ]]; then
    #netperf server preparation...
    server_command="nohup ${netperf_cmd} netserver -p 30000 -D > netperf-server-output.txt 2>&1 &"
    ssh ${server} $server_command
    LogMsg "${server} : Executed: $server_command"

    #Start the netperf client
    client_command="${netperf_cmd} netperf -H ${server} -p 30000 -t TCP_RR -n 32 -l ${test_duration} -D 1 -- -O 'THROUGHPUT, THROUGHPUT_UNITS, MIN_LATENCY, MAX_LATENCY, MEAN_LATENCY, REQUEST_SIZE, RESPONSE_SIZE, STDDEV_LATENCY' > netperf-client-output.txt"
    ssh ${client} $client_command &
    LogMsg "${client} : Executed: $client_command"

    #Start the sar monitor on server.
    server_sar_command="${sar_cmd} -n DEV 1 ${test_duration} > netperf-server-sar-output.txt"
    ssh ${server} $server_sar_command &
    LogMsg "${server} : Executed: $server_sar_command"

    #netperf client preparation...
    client_sar_command="${sar_cmd} -n DEV 1 ${test_duration} > netperf-client-sar-output.txt"
    ssh ${client} $client_sar_command &
    LogMsg "${client} : Executed: $client_sar_command"

    #Wait for tests to finish.
    LogMsg "${client} : Waiting ${test_duration} seconds to finish tests..."
    sleep $test_duration
    LogMsg "${client} : Tests Completed."
    UpdateTestState $ICA_TESTCOMPLETED
    
elif [[ "$test_type" == "maxpps" ]]; then
    #netperf server preparation...
    current_port=30000
    max_port=30031
    while [ $current_port -le $max_port ]; do
        server_command="nohup ${netperf_cmd} netserver -p $current_port -D > netperf-server-output.txt 2>&1 &"
        ssh ${server} $server_command
        LogMsg "Executed: $server_command"
        current_port=$(($current_port+1))
    done

    #netperf client preparation...
    current_job=1
    max_jobs=16
    current_port=30000
    max_port=30031
    rm -rf netperf-client-output.txt
    touch netperf-client-output.txt
    while [ $current_job -le $max_jobs ]; do
        while [ $current_port -le $max_port ]; do
            client_command="nohup ${netperf_cmd} netperf -H ${server} -p $current_port -t TCP_RR -n 32 -l ${test_duration} -D 1 -- -O 'THROUGHPUT, THROUGHPUT_UNITS, MIN_LATENCY, MAX_LATENCY, MEAN_LATENCY, REQUEST_SIZE, RESPONSE_SIZE, STDDEV_LATENCY' >> netperf-client-output.txt 2>&1 &"
            ssh ${client} $client_command
            LogMsg "Executed: $client_command"
            current_port=$(($current_port+1))
        done
        current_job=$(($current_job+1))
    done

    #Start the sar monitor on server.
    server_sar_command="${sar_cmd} -n DEV 1 ${test_duration} > netperf-server-sar-output.txt"
    ssh ${server} $server_sar_command &
    LogMsg "${server} : Executed: $server_sar_command"
    client_sar_command="${sar_cmd} -n DEV 1 ${test_duration} > netperf-client-sar-output.txt"
    ssh ${client} $client_sar_command &
    LogMsg "${client} : Executed: $client_sar_command"
    #Wait for tests to finish.
    LogMsg "${client} : Waiting ${test_duration} seconds to finish tests..."
    sleep $test_duration
    LogMsg "${client} : Tests Completed."
    UpdateTestState $ICA_TESTCOMPLETED
    
else
    LogMsg "Unsupported test mode : $test_type"
    UpdateTestState $ICA_TESTFAILED
fi
exit 0
