#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# This script will install and run DPDK RING PING on client.

HOMEDIR=$(pwd)
export RTE_SDK="${HOMEDIR}/dpdk"
export RTE_TARGET="x86_64-native-linuxapp-gcc"
export DPDK_RING_PING_PATH="${HOMEDIR}/dpdk-ring-ping"

# Source utils.sh
. utils.sh || {
	echo "ERROR: unable to source utils.sh!"
	echo "TestAborted" > state.txt
	exit 0
}

# Source constants file and initialize most common variables
UtilsInit

function run_dpdk_ring_latency () {
	SetTestStateRunning

	if [[ $DPDK_RING_LATENCY_SOURCE_URL =~ ".git" ]] || [[ $DPDK_RING_LATENCY_SOURCE_URL =~ "git:" ]];
	then
		ssh "${1}" git clone "${DPDK_RING_LATENCY_SOURCE_URL}" "${DPDK_RING_PING_PATH}"
		check_exit_status "git clone ${DPDK_RING_LATENCY_SOURCE_URL}" "exit"
		LogMsg "Cloned DPDK_RING from ${DPDK_RING_LATENCY_SOURCE_URL} to ${DPDK_RING_PING_PATH}"
	else
		LogMsg "Provide proper link $DPDK_RING_LATENCY_SOURCE_URL"
		exit 1
	fi

	ssh "${1}" "export RTE_SDK=${RTE_SDK} && export RTE_TARGET=${RTE_TARGET} && cd ${DPDK_RING_PING_PATH} && make"
	check_exit_status "DPDK_RING build on ${1}" "exit"
	LogMsg "Built DPDK_RING"

	ssh "${1}" "cd ${DPDK_RING_PING_PATH}/build/app && ./rping --no-huge --no-pci -n 2 -c 0xc0 -- -t ${DPDK_RING_LATENCY_RUN_TIME} > /tmp/ring-ping.log 2>&1"
	check_exit_status "DPDK_RING run on ${1}" "exit"
	LogMsg "Ran DPDK_RING"

	ring_ping_result=$(ssh "${1}" "tail -1 /tmp/ring-ping.log")
	LogMsg "Last DPDK ring ping line is: ${ring_ping_result}"
	ring_ping_max_latency=$(echo $ring_ping_result | awk '{print $1}')
	if [[ $ring_ping_max_latency -gt $DPDK_RING_LATENCY_MAX ]];then
		LogMsg "DPDK ring latency ${ring_ping_max_latency} higher than ${DPDK_RING_LATENCY_MAX}, failing test case."
		SetTestStateAborted
		exit 1
	fi
}


LogMsg "*********INFO: Script execution Started********"
echo "client-vm : eth0 : ${client}"

run_dpdk_ring_latency "${client}"
SetTestStateCompleted
exit 0
