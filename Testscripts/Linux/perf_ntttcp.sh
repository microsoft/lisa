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

log_folder="ntttcp-${testType}-test-logs"
max_server_threads=64

get_throughput()
{
	throughput=0
	throughput=$(cat ${1} | grep throughput | tail -1 | tr ":" " " | awk '{ print $NF }')
	if [[ $throughput =~ "Gbps" ]];
	then
		throughput=$(echo $throughput | sed 's/Gbps//')
	elif [[ $throughput =~ "Mbps" ]];
	then
		throughput=$(echo "scale=5; $(echo $throughput | sed 's/Mbps//')/1024" | bc)
	elif [[ $throughput =~ "Kbps" ]];
	then
		throughput=$(echo "scale=5; $(echo $throughput | sed 's/Kbps//')/1024/1024" | bc)
	elif [[ $throughput =~ "bps" ]];
	then
		throughput=$(echo "scale=5; $(echo $throughput | sed 's/Kbps//')/1024/1024/1024" | bc)
	else
		throughput=0
	fi
	throughput=`printf %.2f $throughput`
	echo $throughput
}

get_average_latency()
{
	avglatency=0
	avglatency=$(cat ${1} | grep Average | sed 's/.* //')
	if [[ $avglatency =~ "us" ]];
	then
		avglatency=$(echo $avglatency | sed 's/us//')
	elif [[ $avglatency =~ "ms" ]];
	then
		avglatency=$(echo "scale=5; $(echo $avglatency | sed 's/ms//')/1000" | bc)
	elif [[ $avglatency =~ "sec" ]];
	then
		avglatency=$(echo "scale=5; $(echo $avglatency | sed 's/sec//')/1000/1000" | bc)
	else
		avglatency=0
	fi
	avglatency=`printf %.3f $avglatency`
	echo $avglatency
}

get_cyclesperbytes()
{
	cyclesperbytes=0
	cyclesperbytes=$(cat ${1} | grep cycles/byte | tr ":" " " | awk '{ print $NF }')
	if [[ ! $cyclesperbytes ]];
	then
        cyclesperbytes=0
	fi
	cyclesperbytes=`printf %.2f $cyclesperbytes`
	echo $cyclesperbytes
}

run_ntttcp()
{
	i=0
	data_loss=0
	
	ssh ${server} "mkdir -p $log_folder"
	ssh ${client} "mkdir -p $log_folder"
	result_file="${log_folder}/report.csv"
	echo "test_connections,throughput_in_Gbps,cycles/byte,avglatency_in_us" > $result_file
	
	for current_test_threads in $testConnections; do
		if [[ $current_test_threads -lt $max_server_threads ]];
		then
			num_threads_P=$current_test_threads
			num_threads_n=1
		else
			num_threads_P=$max_server_threads
			num_threads_n=$(($current_test_threads/$num_threads_P))
		fi

		LogMsg "============================================="
		LogMsg "Running ${testType} Test: $current_test_threads connections : $num_threads_P X $num_threads_n"
		LogMsg "============================================="

		tx_log_prefix="${testType}-sender-p${num_threads_P}X${num_threads_n}.log"
		rx_log_prefix="${testType}-receiver-p${num_threads_P}X${num_threads_n}.log"
		tx_ntttcp_log_file="$log_folder/ntttcp-${tx_log_prefix}"
		tx_lagscope_log_file="$log_folder/lagscope-${tx_log_prefix}"
		rx_ntttcp_log_file="$log_folder/ntttcp-${rx_log_prefix}"
		
		server_ntttcp_cmd="ulimit -n 204800 && ntttcp -P ${num_threads_P} -t ${testDuration} -e"
		client_ntttcp_cmd="ntttcp -s${server} -P ${num_threads_P} -n ${num_threads_n} -t ${testDuration}"
		ssh ${server} "for i in {1..$testDuration}; do ss -ta | grep ESTA | grep -v ssh | wc -l >> ./$log_folder/tcp-connections-p${num_threads_P}X${num_threads_n}.log; sleep 1; done" &
		
		ssh ${server} "pkill -f ntttcp"
		LogMsg "ServerCmd: $server_ntttcp_cmd > ./$log_folder/ntttcp-${rx_log_prefix}"
		ssh ${server} "${server_ntttcp_cmd}" > "./$log_folder/ntttcp-${rx_log_prefix}" &
		ssh ${server} "pkill -f lagscope"
		ssh ${server} "lagscope -r" &
		ssh ${server} "pkill -f dstat"
		ssh ${server} "dstat -dam" > "./$log_folder/dstat-${rx_log_prefix}" &
		ssh ${server} "pkill -f mpstat"
		ssh ${server} "mpstat -P ALL 1 ${testDuration}" > "./$log_folder/mpstat-${rx_log_prefix}" &

		ulimit -n 204800
		sleep 2		
		sar -n DEV 1 ${testDuration} > "./$log_folder/sar-${tx_log_prefix}" &
		dstat -dam > "./$log_folder/dstat-${tx_log_prefix}" &
		mpstat -P ALL 1 ${testDuration} > "./$log_folder/mpstat-${tx_log_prefix}" &
		lagscope -s${server} -t ${testDuration} -V > "./$log_folder/lagscope-${tx_log_prefix}" &
		LogMsg "ClientCmd: ${client_ntttcp_cmd} > ./${log_folder}/ntttcp-${tx_log_prefix}"
		$client_ntttcp_cmd > "./${log_folder}/ntttcp-${tx_log_prefix}"

		LogMsg "Parsing results for $current_test_threads connections"
		sleep 10
		tx_throughput=$(get_throughput "$tx_ntttcp_log_file")
		rx_throughput=$(get_throughput "$rx_ntttcp_log_file")
		tx_cyclesperbytes=$(get_cyclesperbytes "$tx_ntttcp_log_file")
		avg_latency=$(get_average_latency "$tx_lagscope_log_file")
		rx_cyclesperbytes=$(get_cyclesperbytes "$rx_ntttcp_log_file")
		if [[ $tx_throughput == 0 ]];
		then
			data_loss=`printf %.2f 0`
		else
			data_loss=`printf %.2f $(echo "scale=5; 100*(($tx_throughput-$rx_throughput)/$tx_throughput)" | bc)`
		fi
		data_loss=$data_loss%
		
		LogMsg "Test Results: "
		LogMsg "---------------"
		LogMsg "Throughput in Gbps: Tx: $tx_throughput , Rx: $rx_throughput"
		LogMsg "Cycles/Byte: Tx: $tx_cyclesperbytes , Rx: $rx_cyclesperbytes"
		LogMsg "AvgLaentcy in us: $avg_latency"
		LogMsg "DataLoss in %: $data_loss"
		echo "$current_test_threads,$tx_throughput,$tx_cyclesperbytes,$avg_latency" >> $result_file
		LogMsg "current test finished. wait for next one... "
		i=$(($i + 1))
		sleep 5
	done
}

#Now, start the ntttcp client on client VM.
LogMsg "Now running ${testType} test using NTTTCP"
run_ntttcp

pkill -f dstat
ssh ${server} "pkill -f lagscope"
ssh ${server} "pkill -f dstat"
ssh ${server} "pkill -f mpstat"
column -s, -t $result_file > ./$log_folder/report.log
cp $log_folder/* .
cat report.log
SetTestStateCompleted