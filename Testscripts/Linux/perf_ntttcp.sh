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
ICA_TESTABORTED="TestAborted"           # Error during the setup of the test

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

if [ ! "${server}" ]; then
	errMsg="Please add/provide value for server in constants.sh. server=<server ip>"
	LogMsg "${errMsg}"
	echo "${errMsg}" >> ./summary.log
	UpdateTestState $ICA_TESTABORTED
	exit 1
fi
if [ ! "${client}" ]; then
	errMsg="Please add/provide value for client in constants.sh. client=<client ip>"
	LogMsg "${errMsg}"
	echo "${errMsg}" >> ./summary.log
	UpdateTestState $ICA_TESTABORTED
	exit 1
fi
if [ ! "${testDuration}" ]; then
	errMsg="Please add/provide value for testDuration in constants.sh. testDuration=60"
	LogMsg "${errMsg}"
	echo "${errMsg}" >> ./summary.log
	UpdateTestState $ICA_TESTABORTED
	exit 1
fi

if [ ! "${nicName}" ]; then
	errMsg="Please add/provide value for nicName in constants.sh. nicName=eth0/bond0"
	LogMsg "${errMsg}"
	echo "${errMsg}" >> ./summary.log
	UpdateTestState $ICA_TESTABORTED
	exit 1
fi

# Make & build ntttcp on client and server Machine
LogMsg "Configuring client ${client}..."
Run_SSHCommand "${client}" ". $UTIL_FILE && install_ntttcp ${ntttcpVersion} ${lagscopeVersion}"
if [ $? -ne 0 ]; then
	LogMsg "Error: ntttcp installation failed in ${client}.."
	UpdateTestState "TestAborted"
	exit 1
fi

LogMsg "Configuring server ${server}..."
Run_SSHCommand "${server}" ". $UTIL_FILE && install_ntttcp ${ntttcpVersion} ${lagscopeVersion}"
if [ $? -ne 0 ]; then
	LogMsg "Error: ntttcp installation failed in ${server}.."
	UpdateTestState "TestAborted"
	exit 1
fi

if [[ $(detect_linux_distribution) == coreos ]]; then
	ntttcp_cmd="docker run --network host lisms/ntttcp"
	lagscope_cmd="docker run --network host lisms/lagscope"
	mpstat_cmd="docker run --network host lisms/toolbox mpstat"
	dstat_cmd="docker run --network host lisms/toolbox dstat"
	sar_cmd="docker run --network host lisms/toolbox sar"
	Run_SSHCommand "${server}" ". $UTIL_FILE && Delete_Containers"
	Run_SSHCommand "${client}" ". $UTIL_FILE && Delete_Containers"
else
	ntttcp_cmd="ntttcp"
	lagscope_cmd="lagscope"
	mpstat_cmd="mpstat"
	dstat_cmd="dstat"
	sar_cmd="sar"
fi

bc_cmd=$(echo $(Get_BC_Command))
log_folder="$(pwd)/ntttcp-${testType}-test-logs"
max_server_threads=64

Get_Throughput()
{
	throughput=$(grep 'INFO.*throughput' "${1}" | tail -1 | tr ":" " " | awk '{ print $NF }')
	if [[ $throughput =~ "Gbps" ]];
	then
		throughput=$(echo "$throughput" | sed 's/Gbps//')
	elif [[ $throughput =~ "Mbps" ]];
	then
		throughput=$(echo "scale=5; $(echo "$throughput" | sed 's/Mbps//')/1024" | ${bc_cmd})
	elif [[ $throughput =~ "Kbps" ]];
	then
		throughput=$(echo "scale=5; $(echo "$throughput" | sed 's/Kbps//')/1024/1024" | ${bc_cmd})
	elif [[ $throughput =~ "bps" ]];
	then
		throughput=$(echo "scale=5; $(echo "$throughput" | sed 's/Kbps//')/1024/1024/1024" | ${bc_cmd})
	else
		throughput=0
	fi
	throughput=$(printf %.2f $throughput)
	echo "$throughput"
}

Get_Average_Latency()
{
	avglatency=$(grep Average "${1}" | sed 's/.* //')
	if [[ $avglatency =~ "us" ]];
	then
		avglatency=$(echo "$avglatency" | sed 's/us//')
	elif [[ $avglatency =~ "ms" ]];
	then
		avglatency=$(echo "scale=5; $(echo "$avglatency" | sed 's/ms//')/1000" | ${bc_cmd})
	elif [[ $avglatency =~ "sec" ]];
	then
		avglatency=$(echo "scale=5; $(echo "$avglatency" | sed 's/sec//')/1000/1000" | ${bc_cmd})
	else
		avglatency=0
	fi
	avglatency=$(printf %.3f $avglatency)
	echo "$avglatency"
}

Get_CyclesPerBytes()
{
	cyclesperbytes=$(grep "cycles/byte" "${1}" | tr ":" " " | awk '{ print $NF }')
	if [[ ! $cyclesperbytes ]];
	then
		cyclesperbytes=0
	fi
	cyclesperbytes=$(printf %.2f $cyclesperbytes)
	echo "$cyclesperbytes"
}

Get_ConCreatedTime()
{
	concreatedtime_us=$(grep "connections created in" "${1}" | tr ":" " " | awk '{ print $(NF-1) }')
	if [[ ! $concreatedtime_us ]];
	then
		concreatedtime_us=0
	fi
	echo  "$concreatedtime_us"
}

Get_RetransSegs()
{
	retrans_segs=$(grep "retrans segs" "${1}" | tr ":" " " | awk '{ print $NF }')
	if [[ ! $retrans_segs ]];
	then
		retrans_segs=0
	fi
	echo  "$retrans_segs"
}

Get_PktsInterrupts()
{
	pktsinterrupts=$(grep "pkts/interrupt" "${1}" | tr ":" " " | awk '{ print $NF }')
	if [[ ! $pktsinterrupts ]];
	then
		pktsinterrupts=0
	fi
	pktsinterrupts=$(printf %.2f $pktsinterrupts)
	echo "$pktsinterrupts"
}

Get_Packets()
{
	packets=$(grep "${2}" "${1}" | tr ":" " " | awk '{ print $NF }')
	if [[ ! $packets ]];
	then
		packets=0
	fi
	echo "$packets"
}

Get_VFName()
{
	ntttcpVersion="${1}"
	ip="${2}"
	ntttcp_cmd="${3}"
	if [ $ntttcpVersion ] && [[ $ntttcpVersion == v* ]]; then
		currentVersion="${ntttcpVersion:1}"
	else
		currentVersion="${ntttcpVersion}"
	fi
	# The -K and -I options are supported if the ntttcp version is greater than 1.4.0, or equal to 1.4.0
	# -K changed into --show-nic-packets, -I changed into --show-dev-interrupts in master branch
	if [ $currentVersion ] && ( [ $currentVersion \> "1.4.0" ] || [ $currentVersion == "1.4.0" ] || [ $currentVersion == "master" ] ); then
		if [[ -d /sys/firmware/efi ]]; then
		# This is the case of VM gen 2
			vf_interface=$(find /sys/devices/* -name "*${nicName}" | grep pci | sed 's/\// /g' | awk '{print $11}')
		else
		# VM gen 1 case
			vf_interface=$(find /sys/devices/* -name "*${nicName}" | grep pci | sed 's/\// /g' | awk '{print $12}')
		fi
		if [[ $vf_interface ]]; then
			if [[ $currentVersion == "master" ]]; then
				ntttcp_cmd="$ntttcp_cmd --show-nic-packets $vf_interface --show-dev-interrupts mlx"
			else
				ntttcp_cmd="$ntttcp_cmd -K $vf_interface -I mlx"
			fi
		else
			if [[ $currentVersion == "master" ]]; then
				ntttcp_cmd="$ntttcp_cmd --show-nic-packets ${nicName} --show-dev-interrupts Hypervisor callback interrupts"
			else
				ntttcp_cmd="$ntttcp_cmd -K ${nicName} -I Hypervisor callback interrupts"
			fi
		fi
	fi
	echo "$ntttcp_cmd"
}

Run_Ntttcp()
{
	i=0
	data_loss=0
	Kill_Process "${server}" ntttcp
	Kill_Process "${client}" ntttcp

	# Disable firewalld
	Run_SSHCommand "${client}" "service firewalld stop"
	Run_SSHCommand "${server}" "service firewalld stop"

	Run_SSHCommand "${server}" "mkdir -p ${log_folder}"
	Run_SSHCommand "${client}" "mkdir -p ${log_folder}"
	result_file="${log_folder}/report.csv"
	if [[ $testType == "udp" ]];
	then
		bufferLength=$(($bufferLength/1024))
		echo "test_connections,tx_throughput_in_Gbps,rx_throughput_in_Gbps,datagram_loss_in_%" > "${result_file}"
		core_mem_set_cmd="sysctl -w net.core.rmem_max=67108864; sysctl -w net.core.rmem_default=67108864; sysctl -w net.core.wmem_default=67108864; sysctl -w net.core.wmem_max=67108864"
		Run_SSHCommand "${server}" "${core_mem_set_cmd}"
		Run_SSHCommand "${client}" "${core_mem_set_cmd}"
	else
		testType="tcp"
		# Set sysctl config for creating more than 40960 connections
		core_mem_set_cmd="sysctl -w kernel.pid_max=122880; sysctl -w vm.max_map_count=655300; sysctl -w net.ipv4.ip_local_port_range='1024 65535'"
		Run_SSHCommand "${client}" "${core_mem_set_cmd}"
		echo "test_connections,throughput_in_Gbps,cycles/byte_sender,cycles/byte_receiver,avglatency_in_us,txpackets_sender,rxpackets_sender,pktsInterrupt_sender,concreatedtime_us,retrans_segs" > "${result_file}"
	fi

	IFS=',' read -r -a array <<< "$client"
	client_count=${#array[@]}
	if [ "$client_count" -gt 1 ];
	then
		mode="multi-clients"
	fi
	for current_test_threads in "${testConnections[@]}"; do
		test_threads=$(($current_test_threads/$client_count))
		if [[ $test_threads -lt $max_server_threads ]];
		then
			num_threads_P=$(($test_threads))
			num_threads_n=1
		else
			num_threads_P=$max_server_threads
			num_threads_n=$(($test_threads/$num_threads_P))
		fi

		if [[ $testType == "udp" ]];
		then
			tx_log_prefix="sender-${testType}-${bufferLength}k-p${num_threads_P}X${num_threads_n}.log"
			rx_log_prefix="receiver-${testType}-${bufferLength}k-p${num_threads_P}X${num_threads_n}.log"
			run_msg="Running ${testType} ${bufferLength}k Test: $current_test_threads connections : $num_threads_P X $num_threads_n X $client_count clients"
			server_ntttcp_cmd="ulimit -n 204800 && ${ntttcp_cmd} -r${server} -u -b ${bufferLength}k -P ${num_threads_P} -t ${testDuration} -e -W 1 -C 1"
			if [[ "$mode" == "multi-clients" ]];
			then
				server_ntttcp_cmd+=" -M"
			fi
			client_ntttcp_cmd="ulimit -n 204800 && ${ntttcp_cmd} -s${server} -u -b ${bufferLength}k -P ${num_threads_P} -n ${num_threads_n} -t ${testDuration} -W 1 -C 1"
		else
			tx_log_prefix="sender-${testType}-p${num_threads_P}X${num_threads_n}.log"
			rx_log_prefix="receiver-${testType}-p${num_threads_P}X${num_threads_n}.log"
			run_msg="Running ${testType} Test: $current_test_threads connections : $num_threads_P X $num_threads_n X $client_count clients"
			server_ntttcp_cmd="ulimit -n 204800 && ${ntttcp_cmd} -r${server} -P ${num_threads_P} -t ${testDuration} -e -W 1 -C 1"
			if [[ "$mode" == "multi-clients" ]];
			then
				server_ntttcp_cmd+=" -M"
			fi
			client_ntttcp_cmd="ulimit -n 204800 && ${ntttcp_cmd} -s${server} -P ${num_threads_P} -n ${num_threads_n} -t ${testDuration} -W 1 -C 1"
			Run_SSHCommand "${server}" "for i in {1..$testDuration}; do ss -ta | grep ESTA | grep -v ssh | wc -l >> ${log_folder}/tcp-connections-p${num_threads_P}X${num_threads_n}.log; sleep 1; done" &
		fi


		server_ntttcp_cmd=$(Get_VFName "${ntttcpVersion}" "${server}" "${server_ntttcp_cmd}")

		LogMsg "============================================="
		LogMsg "${run_msg}"
		LogMsg "============================================="
		tx_ntttcp_log_file="${log_folder}/ntttcp-${tx_log_prefix}"
		tx_lagscope_log_file="${log_folder}/lagscope-${tx_log_prefix}"
		rx_ntttcp_log_file="${log_folder}/ntttcp-${rx_log_prefix}"
		tx_ntttcp_log_files=()
		tx_lagscope_log_files=()
		Kill_Process "${server}" ntttcp
		Kill_Process "${client}" ntttcp
		LogMsg "ServerCmd: $server_ntttcp_cmd > ${log_folder}/ntttcp-${rx_log_prefix}"
		ssh "${server}" "${server_ntttcp_cmd} > ${log_folder}/ntttcp-${rx_log_prefix} &" &
		Kill_Process "${server}" lagscope
		Run_SSHCommand "${server}" "${lagscope_cmd} -r" &
		Kill_Process "${server}" dstat
		Run_SSHCommand "${server}" "${dstat_cmd} -dam" > "${log_folder}/dstat-${rx_log_prefix}" &
		Kill_Process "${server}" mpstat
		Run_SSHCommand "${server}" "${mpstat_cmd} -P ALL 1 ${testDuration}" > "${log_folder}/mpstat-${rx_log_prefix}" &

		sleep 2
		IFS=',' read -r -a array <<< "${client}"
		for ip in "${array[@]}"
		do
			Kill_Process "${ip}" sar
			Kill_Process "${ip}" dstat
			Kill_Process "${ip}" mpstat
			Kill_Process "${ip}" lagscope
			ssh "${ip}" "${sar_cmd} -n DEV 1 ${testDuration}" > "${log_folder}/sar-${ip}-${tx_log_prefix}" &
			ssh "${ip}" "${dstat_cmd} -dam" > "${log_folder}/dstat-${ip}-${tx_log_prefix}" &
			ssh "${ip}" "${mpstat_cmd} -P ALL 1 ${testDuration}" > "${log_folder}/mpstat-${ip}-${tx_log_prefix}" &
			ssh "${ip}" "${lagscope_cmd} -s${server} -t${testDuration}" -V > "${log_folder}/lagscope-${ip}-${tx_log_prefix}" &
			tx_lagscope_log_files+=("${log_folder}/lagscope-${ip}-${tx_log_prefix}")
		done

		if [[ "$mode" == "multi-clients" ]];
		then
			IFS=',' read -r -a array <<< "${client}"
			index=$(($client_count -1))
			client_ntttcp_raw_cmd="$client_ntttcp_cmd"
			for ip in "${array[@]:0:$index}"
			do
				client_ntttcp_cmd=$(Get_VFName "${ntttcpVersion}" "${ip}" "${client_ntttcp_raw_cmd}")
				LogMsg "Execute ${client_ntttcp_cmd} on ${ip}"
				ssh "${ip}" "${client_ntttcp_cmd}" > "${log_folder}/ntttcp-${ip}-${tx_log_prefix}" &
				tx_ntttcp_log_files+=("${log_folder}/ntttcp-${ip}-${tx_log_prefix}")
				sleep 5
			done

			client_ntttcp_cmd=$(Get_VFName "${ntttcpVersion}" "${array[$(($index))]}" "${client_ntttcp_raw_cmd}")
			client_ntttcp_cmd+=" -L"
			LogMsg "Execute ${client_ntttcp_cmd} on ${array[$(($index))]}"
			ssh "${array[$(($index))]}" "${client_ntttcp_cmd}"  > "${log_folder}/ntttcp-${array[$(($index))]}-${tx_log_prefix}"
			tx_ntttcp_log_files+=("${log_folder}/ntttcp-${array[$(($index))]}-${tx_log_prefix}")
		else
			client_ntttcp_cmd=$(Get_VFName "${ntttcpVersion}" "${client}" "${client_ntttcp_cmd}")
			LogMsg "Execute ${client_ntttcp_cmd} on ${client}"
			ssh "${client}" "${client_ntttcp_cmd}" > "${log_folder}/ntttcp-${tx_log_prefix}"
			tx_ntttcp_log_files="${log_folder}/ntttcp-${tx_log_prefix}"
		fi
		scp root@"${server}":"${log_folder}/ntttcp-${rx_log_prefix}" "${log_folder}/ntttcp-${rx_log_prefix}"
		LogMsg "Parsing results for $current_test_threads connections"
		sleep 10
		tx_throughput_value=0.0
		tx_cyclesperbytes_value=0.0
		txpackets_sender_value=0.0
		rxpackets_sender_value=0.0
		pktsInterrupt_sender_value=0.0
		avg_latency_value=0.0
		retrans_segs_value=0
		concreatedtime_us_value=0.0
		for tx_ntttcp_log_file in "${tx_ntttcp_log_files[@]}";
		do
			tx_throughput=$(Get_Throughput "$tx_ntttcp_log_file")
			tx_throughput_value=$(echo "$tx_throughput + $tx_throughput_value" | ${bc_cmd})
			tx_cyclesperbytes=$(Get_CyclesPerBytes "$tx_ntttcp_log_file")
			tx_cyclesperbytes_value=$(echo "$tx_cyclesperbytes + $tx_cyclesperbytes_value" | ${bc_cmd})
			txpackets_sender=$(Get_Packets "$tx_ntttcp_log_file" "tx_packets")
			txpackets_sender_value=$(echo "$txpackets_sender + $txpackets_sender_value" | ${bc_cmd})
			rxpackets_sender=$(Get_Packets "$tx_ntttcp_log_file" "rx_packets")
			rxpackets_sender_value=$(echo "$rxpackets_sender + $rxpackets_sender_value" | ${bc_cmd})
			pktsInterrupt_sender=$(Get_PktsInterrupts "$tx_ntttcp_log_file")
			pktsInterrupt_sender_value=$(echo "$pktsInterrupt_sender + $pktsInterrupt_sender_value" | ${bc_cmd})
			concreatedtime_us=$(Get_ConCreatedTime "$tx_ntttcp_log_file")
			concreatedtime_us_value=$(echo "$concreatedtime_us + $concreatedtime_us_value" | ${bc_cmd})
			retrans_segs=$(Get_RetransSegs "$tx_ntttcp_log_file")
			retrans_segs_value=$(echo "$retrans_segs + $retrans_segs_value" | ${bc_cmd})
		done
		tx_throughput=$tx_throughput_value
		rx_throughput=$(Get_Throughput "$rx_ntttcp_log_file")
		tx_cyclesperbytes=$tx_cyclesperbytes_value
		retrans_segs=$retrans_segs_value
		concreatedtime_us=$(echo "$concreatedtime_us_value/${#tx_ntttcp_log_files[@]}" | bc)
		for tx_lagscope_log_file in "${tx_lagscope_log_files[@]}";
		do
			avg_latency=$(Get_Average_Latency "$tx_lagscope_log_file")
			avg_latency_value=$(echo "$avg_latency + $avg_latency_value" | ${bc_cmd})
		done
		avg_latency=$avg_latency_value
		rx_cyclesperbytes=$(Get_CyclesPerBytes "$rx_ntttcp_log_file")
		if [[ $tx_throughput == "0.00" ]];
		then
			data_loss=$(printf %.2f 0)
		else
			data_loss=$(printf %.2f $(echo "scale=5; 100*(($tx_throughput-$rx_throughput)/$tx_throughput)" | ${bc_cmd}))
		fi
		txpackets_sender=$txpackets_sender_value
		rxpackets_sender=$rxpackets_sender_value
		txpackets_receiver=$(Get_Packets "$rx_ntttcp_log_file" "tx_packets")
		rxpackets_receiver=$(Get_Packets "$rx_ntttcp_log_file" "rx_packets")
		pktsInterrupt_sender=$pktsInterrupt_sender_value
		pktsInterrupt_receiver=$(Get_PktsInterrupts "$rx_ntttcp_log_file")

		LogMsg "Test Results: "
		LogMsg "---------------"
		LogMsg "Throughput in Gbps: Tx: $tx_throughput , Rx: $rx_throughput"
		LogMsg "Cycles/Byte: Tx: $tx_cyclesperbytes , Rx: $rx_cyclesperbytes"
		LogMsg "AvgLatency in us: $avg_latency"
		LogMsg "DataLoss in %: $data_loss"
		LogMsg "tx_packets/rx_packets on sender: $txpackets_sender / $rxpackets_sender"
		LogMsg "tx_packets/rx_packets on receiver: $txpackets_receiver / $rxpackets_receiver"
		LogMsg "pkts/interrupt:  Tx: $pktsInterrupt_sender , Rx: $pktsInterrupt_receiver"
		LogMsg "Connections created time: $concreatedtime_us"
		LogMsg "Retrasmit segments: $retrans_segs"

		if [[ $testType == "udp" ]];
		then
			echo "$current_test_threads,$tx_throughput,$rx_throughput,$data_loss" >> "${result_file}"
		else
			testType="tcp"
			echo "$current_test_threads,$tx_throughput,$tx_cyclesperbytes,$rx_cyclesperbytes,$avg_latency,$txpackets_sender,$rxpackets_sender,$pktsInterrupt_sender,$concreatedtime_us,$retrans_segs" >> "${result_file}"
		fi
		LogMsg "current test finished. wait for next one... "
		i=$(($i + 1))
		sleep 15
	done
}

# Start the ntttcp client on client VM
LogMsg "Now running ${testType} test using NTTTCP"
Run_Ntttcp

Kill_Process "${client}" dstat
Kill_Process "${server}" lagscope
Kill_Process "${server}" dstat
Kill_Process "${server}" mpstat
column -s, -t "${result_file}" > "${log_folder}"/report.log
cp "${log_folder}"/* .
cat report.log
SetTestStateCompleted
