#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# This script verifies XDP Action - TX or DROP
# For DROP/ABORTED Action verification script will compare number of ping packets
#		lossed before XDP DROP/ABORTED action and after XDP DROP/ABORTED action
# For TX Action verification script will start ping on server and measure the packets captured by tcpdump
#		Expected result: 0 packets should be captured by tcpdump after TX action as this action
#		will return all ping packets to sender at hardware level


# Helper function
# This function will start xdpdump on client
# and ping from server on eth1 network interface
function ping_test () {
	local logSuffix=$1
	# https://lore.kernel.org/lkml/1579558957-62496-3-git-send-email-haiyangz@microsoft.com/t/
	LogMsg "XDP program cannot run with LRO (RSC) enabled, disable LRO before running XDP"
	ssh ${client} "ethtool -K ${nicName} lro off"
	xdpdumpCommand="cd bpf-samples/xdpdump && timeout 20 ./xdpdump -i ${nicName} > ~/xdpdumpout_${logSuffix}.txt 2>&1"
	LogMsg "Starting xdpdump on ${client} with command: ${xdpdumpCommand}"
	ssh -f ${client} "sh -c '${xdpdumpCommand}'"

	LogMsg "Starting ping on ${server} with command: ping -I ${nicName} -c 10 ${clientSecondIP} > ~/pingOut_${logSuffix}.txt"
	ssh ${server} "ping -I ${nicName} -c 10 ${clientSecondIP} > ~/pingOut_${logSuffix}.txt"
	check_exit_status "ping test ${logSuffix} XDPDump-${ACTION} config"
	# Cleanup xdpdump process
	killall xdpdump
}

# Helper function
# This function will start tcpdump on client and start ping_test
function ping_with_tcpdump () {
	local logSuffix=$1
	LogMsg "Ips client $client server $server"
	# Start tcpdump
	LogMsg "Starting tcpdump on ${client} with command timeout 10 tcpdump -i eth1 icmp -w tcpdumptest_${logSuffix}.pcap"
	ssh ${client} "sh -c 'timeout 10 tcpdump -i eth1 icmp -w tcpdumptest_${logSuffix}.pcap &'"
	ping_test $logSuffix
}

UTIL_FILE="./utils.sh"

# Source utils.sh
. ${UTIL_FILE} || {
		echo "ERROR: unable to source ${UTIL_FILE}!"
		echo "TestAborted" > state.txt
		exit 0
}

# Source constants file and initialize most common variables
UtilsInit

# Script start from here
LogMsg "*********INFO: Script Execution Started********"

# check for client and server ips are present
for ip in ${client} ${server}
do
	CheckIP ${ip}
	if [ $? -eq 1 ]; then
		LogErr "ERROR: Please provide valide client and server ip. Invalid ip: ${ip}"
		SetTestStateAborted
		exit 1
	fi
done

beforeString="before"
afterString="after"
packetLossInNetwork=10

if [ "${ACTION}" == "DROP" ] || [ "${ACTION}" == "ABORTED" ];then
	LogMsg "Initializing validation for XDP Action ${ACTION}"

	# Ping test before changing action
	ping_test $beforeString

	# Build xdpdump with DROP/ABORTED Config
	LogMsg "Build XDPDump with ${ACTION} flag"
	ssh ${client} "cd bpf-samples/xdpdump && make clean && CFLAGS='-D __ACTION_${ACTION}__ -I../libbpf/src/root/usr/include' make"
	check_exit_status "Building xdpdump with ${ACTION} config"

	# Ping test after changing action
	ping_test $afterString

	LogMsg "Starting analysis on number of ping packets drop.."
	packetDropBefore=$(ssh ${server} "grep -oP '\d+(?=% packet loss)' ~/pingOut_${beforeString}.txt")
	LogMsg "Packet drop $beforeString $packetDropBefore"
	packetDropAfter=$(ssh ${server} "grep -oP '\d+(?=% packet loss)' ~/pingOut_${afterString}.txt")
	LogMsg "Packet drop $afterString $packetDropAfter"

	if [ $((packetDropBefore + packetLossInNetwork)) -lt $((packetDropAfter)) ];then
		LogMsg "Test case executed successfully"
		SetTestStateCompleted
		exit 0
	else
		LogErr "Ping packets are not dropped. Please check pingOut logs"
		SetTestStateFailed
		exit 1
	fi
elif [ "${ACTION}" == "TX" ];then
	LogMsg "Initializing validation for XDP Action ${ACTION}"

	# Run ping from server and tcpdump with XDPDUmp on client
	ping_with_tcpdump $beforeString

	LogMsg "Build XDPDump with TX flag"
	ssh ${client} "cd bpf-samples/xdpdump && make clean && CFLAGS='-D __ACTION_TX__ -I../libbpf/src/root/usr/include' make"
	check_exit_status "Building xdpdump with TX config"

	# Run Ping from server and tcpdump with xdpdump on client
	# Get count of tcpdump and ping packets
	ping_with_tcpdump $afterString

	packetDropBefore=$(ssh ${server} "grep -oP '\d+(?=% packet loss)' ~/pingOut_${beforeString}.txt")
	LogMsg "Packet drop $beforeString $packetDropBefore"
	packetDropAfter=$(ssh ${server} "grep -oP '\d+(?=% packet loss)' ~/pingOut_${afterString}.txt")
	LogMsg "Packet drop $afterString $packetDropAfter"

	if [ $((packetDropAfter - packetDropBefore)) -le $packetLossInNetwork ];then
		LogMsg "XDP Action does not impact ICMP packet loss"
	else
		LogMsg "More Packets dropped than expected please check pingOut logs"
		SetTestStateFailed
		exit 1
	fi

	LogMsg "Starting analysis on packets captured by tcpdump application"
	tcpdumpCountAfter=$(ssh ${client} "tcpdump -r tcpdumptest_${afterString}.pcap 2>/dev/null | wc -l")

	if [ $tcpdumpCountAfter -gt 0 ];then
		LogErr "ICMP packets captured by tcpdump. Please check xdpAction.log."
		SetTestStateFailed
		exit 1
	else
		LogMsg "XDPDump with TX ran as ping server and requested back all packets to sender"
		SetTestStateCompleted
		exit 0
	fi

else
	LogErr "Please provide ACTION variable: DROP/TX/ABORTED"
	SetTestStateFailed
	exit 1
fi
