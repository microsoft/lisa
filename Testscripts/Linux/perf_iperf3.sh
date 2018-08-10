#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# 
#######################################################################

#######################################################################
#
# perf_IPERF3.sh
# Description:
#	Download and run IPERF3 network performance tests.
#	This script needs to be run on client VM.
#
# Supported Distros:
#	Ubuntu 16.04
#######################################################################

CONSTANTS_FILE="./constants.sh"
UTIL_FILE="./utils.sh"
ICA_TESTRUNNING="TestRunning"	  # The test is running
ICA_TESTCOMPLETED="TestCompleted"  # The test completed successfully
ICA_TESTABORTED="TestAborted"	  # Error during the setup of the test
ICA_TESTFAILED="TestFailed"		# Error occurred during the test
touch ./IPERF3Test.log

LogMsg()
{
	echo `date "+%b %d %Y %T"` : "${1}"	# Add the time stamp to the log message
	echo "${1}" >> ./IPERF3Test.log
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

if [ ! ${testType} ]; then
	errMsg="Please add/provide value for testType in constants.sh. testType=tcp/udp"
	LogMsg "${errMsg}"
	echo "${errMsg}" >> ./summary.log
	UpdateTestState $ICA_TESTABORTED
	exit 1
fi

if [ ! ${max_parallel_connections_per_instance} ]; then
	errMsg="Please add/provide value for max_parallel_connections_per_instance in constants.sh. max_parallel_connections_per_instance=60"
	LogMsg "${errMsg}"
	echo "${errMsg}" >> ./summary.log
	UpdateTestState $ICA_TESTABORTED
	exit 1
fi

if [ ! ${connections} ]; then
	errMsg="Please add/provide value for connections in constants.sh. connections=(1 2 4 8 ....)"
	LogMsg "${errMsg}"
	echo "${errMsg}" >> ./summary.log
	UpdateTestState $ICA_TESTABORTED
	exit 1
fi

if [ ! ${bufferLengths} ]; then
	errMsg="Please add/provide value for bufferLengths in constants.sh. bufferLengths=(1 8). Note buffer lenghs are in Bytest"
	LogMsg "${errMsg}"
	echo "${errMsg}" >> ./summary.log
	UpdateTestState $ICA_TESTABORTED
	exit 1
fi

if [ ! ${IPversion} ]; then
	errMsg="Please add/provide value for IPversion in constants.sh. IPversion=4/6."
	LogMsg "${errMsg}"
	echo "${errMsg}" >> ./summary.log
	UpdateTestState $ICA_TESTABORTED
	exit 1
fi

if [ $IPversion -eq 6 ]; then
	if [ ! ${serverIpv6} ]; then
		errMsg="Please add/provide value for serverIpv6 in constants.sh"
		LogMsg "${errMsg}"
		echo "${errMsg}" >> ./summary.log
		UpdateTestState $ICA_TESTABORTED
		exit 1
	fi
	if [ ! ${clientIpv6} ]; then
		errMsg="Please add/provide value for clientIpv6 in constants.sh."
		LogMsg "${errMsg}"
		echo "${errMsg}" >> ./summary.log
		UpdateTestState $ICA_TESTABORTED
		exit 1
	fi
fi


#connections=(64 128)
#BufferLenghts are in Bytes
#max_parallel_connections_per_instance=64
#Make & build IPERF3 on client and server Machine

LogMsg "Configuring client ${client}..."
ssh ${client} ". $UTIL_FILE && install_iperf3 $IPversion"
ssh ${client} "which iperf3"
if [ $? -ne 0 ]; then
	LogMsg "Error: iperf installation failed in ${client}.."
	UpdateTestState "TestAborted"
	exit 1
fi

LogMsg "Configuring server ${server}..."
ssh ${server} ". $UTIL_FILE && install_iperf3 $IPversion"
ssh ${server} "which iperf3"
if [ $? -ne 0 ]; then
	LogMsg "Error: iperf installation failed in ${server}.."
	UpdateTestState "TestAborted"
	exit 1
fi

ssh ${server} "rm -rf iperf-server-*"
ssh ${client} "rm -rf iperf-client-*"
ssh ${client} "rm -rf iperf-server-*"


#connections=(1 2 4 8 16 32 64 128 256 512 1024)
#BufferLenghts are in K
#bufferLenghs=(1 8)

for current_buffer in "${bufferLengths[@]}"; do
	for current_test_connections in "${connections[@]}"; do
		if [ $current_test_connections -lt $max_parallel_connections_per_instance ]; then
			num_threads_P=$current_test_connections
			num_threads_n=1
		else
			num_threads_P=$max_parallel_connections_per_instance
			num_threads_n=$(($current_test_connections / $num_threads_P))
		fi
		
		ssh ${server} "killall iperf3"
		ssh ${client} "killall iperf3"
		LogMsg "Starting $num_threads_n iperf3 server instances on $server.."
		startPort=750
		currentPort=$startPort
		currentIperfInstanses=0
		while [ $currentIperfInstanses -lt $num_threads_n ]; do
			currentIperfInstanses=$(($currentIperfInstanses+1))
			serverCommand="iperf3 -s -1 -J -i10 -f g -p ${currentPort} > iperf-server-${testType}-IPv${IPversion}-buffer-${current_buffer}-conn-$current_test_connections-instance-${currentIperfInstanses}.txt 2>&1"
			ssh ${server} $serverCommand &
			LogMsg "Executed: $serverCommand"
			currentPort=$(($currentPort+1))
			sleep 0.1
		done

		LogMsg "$num_threads_n iperf server instances started on $server.."
		sleep 5
		LogMsg "Starting client.."
		startPort=750
		currentPort=$startPort
		currentIperfInstanses=0
		if [ $IPversion -eq 4 ]; then
			testServer=$server
		else
			testServer=$serverIpv6
		fi
		#ssh ${client} "./sar-top.sh ${testDuration} $current_test_connections root" &
		#ssh ${server} "./sar-top.sh ${testDuration} $current_test_connections root" &
		while [ $currentIperfInstanses -lt $num_threads_n ]; do
			currentIperfInstanses=$(($currentIperfInstanses+1))

			if [[ "$testType" == "udp" ]]; then
				clientCommand="iperf3 -c $testServer -u -b 0 -J -f g -i10 -l ${current_buffer} -t ${testDuration} -p ${currentPort} -P $num_threads_P -${IPversion} > iperf-client-${testType}-IPv${IPversion}-buffer-${current_buffer}-conn-$current_test_connections-instance-${currentIperfInstanses}.txt 2>&1"
			fi
			if [[ "$testType" == "tcp" ]]; then
				clientCommand="iperf3 -c $testServer -b 0 -J -f g -i10 -l ${current_buffer} -t ${testDuration} -p ${currentPort} -P $num_threads_P -${IPversion} > iperf-client-${testType}-IPv${IPversion}-buffer-${current_buffer}-conn-$current_test_connections-instance-${currentIperfInstanses}.txt 2>&1"
			fi
			
			ssh ${client} $clientCommand &
			LogMsg "Executed: $clientCommand"
			currentPort=$(($currentPort+1))
			sleep 0.1
		done
		LogMsg "Iperf3 running buffer ${current_buffer}Bytes $num_threads_P X $num_threads_n ..."
		sleep ${testDuration}
		timeoutSeconds=900
		sleep 5
		var=`ps -C "iperf3 -c" --no-headers | wc -l`
		echo $var
		while [[ $var -gt 0 ]]; do
			timeoutSeconds=`expr $timeoutSeconds - 1`
			if [ $timeoutSeconds -eq 0 ]; then
				LogMsg "Iperf3 running buffer ${current_buffer}K $num_threads_P X $num_threads_n. Timeout."
				LogMsg "killing all iperf3 client threads."
				killall iperf3
				sleep 1
			else
				sleep 1
				var=`ps -C "iperf3 -c" --no-headers | wc -l`
				LogMsg "Iperf3 running buffer ${current_buffer}K $num_threads_P X $num_threads_n. Waiting to finish $var instances."
			fi
		done
		#Sleep extra 5 seconds.
		sleep 5
		LogMsg "Iperf3 Finished buffer ${current_buffer}  $num_threads_P X $num_threads_n ..."
	done
done
scp ${server}:iperf-server-* ./
UpdateTestState ICA_TESTCOMPLETED
