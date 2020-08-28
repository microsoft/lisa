#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# This script verifies XDP working with different MTU sizes

# This function will change MTU of device
function change_mtu(){
    if [ -z "${1}" -o -z "${2}" -o -z "${3}" ]; then
        LogErr "ERROR: must provide ip, interface and size of new MTU"
        SetTestStateAborted
        exit 0
    fi
    local ip="${1}"
    local iface="${2}"
    local newMtu="${3}"
    local getMtuCmd="cat /sys/class/net/${iface}/mtu"

    mtuSizeBefore=$(ssh ${ip} "${getMtuCmd}")
    LogMsg "Current MTU Size: ${mtuSizeBefore}"

    local command="ip link set dev ${iface} mtu ${newMtu}"
    LogMsg "Changing MTU of ${iface} to ${newMtu}"
    ssh ${ip} "${command}"
    check_exit_status "MTU Change of ${ip}:${iface} to ${newMtu}" "exit"

    LogMsg "Restarting device"
    ssh ${ip} "ip link set dev ${iface} down"
    check_exit_status "${iface} Device is Down"
    ssh ${ip} "ip link set dev ${iface} up"
    check_exit_status "${iface} Device is Up"

    # verify change in MTU
    mtu_size_after=$(ssh ${ip} "${getMtuCmd}")
    if [[ $mtu_size_after -ne $newMtu ]]; then
        LogErr "Failed to set MTU on ${ip} to ${newMtu}"
        SetTestStateAborted
        exit 1
    fi
    LogMsg "MTU Successfully changed to ${newMtu}"
}

# Helper function
# This function will start xdpdump on client
# and ping from server on eth1 network interface with provided packetSize 3470
function ping_test() {
    local packetSize=$1
    # https://lore.kernel.org/lkml/1579558957-62496-3-git-send-email-haiyangz@microsoft.com/t/
    LogMsg "XDP program cannot run with LRO (RSC) enabled, disable LRO before running XDP"
    ssh ${client} "ethtool -K ${nicName} lro off"
    xdpdumpCommand="cd bpf-samples/xdpdump && timeout 10 ./xdpdump -i ${nicName} > ~/xdpdumpout_${packetSize}.txt 2>&1"
    LogMsg "Starting xdpdump on ${client} with command: ${xdpdumpCommand}"
    ssh ${client} "sh -c '${xdpdumpCommand} &'"
    # ping -M do -c 10 -s 3470 ${clientSecondIP}
    LogMsg "Starting ping on ${server} with command: ping -I ${nicName} -c 10 -M do -s ${packetSize} ${clientSecondIP} > ~/pingOut_${logSuffix}.txt"
    ssh ${server} "ping -I ${nicName} -c 10 -M do -s ${packetSize} ${clientSecondIP} > ~/pingOut_${packetSize}.txt"
    check_exit_status "ping test with packet size ${packetSize}"
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

# Start XDPDump Setup
if [ -f "./XDPDumpSetup.sh" ];then
    LogMsg "Starting XDPDump setup"
    bash ./XDPDumpSetup.sh
    SetTestStateRunning
else
    LogErr "XDPDumpSetup.sh is not accessible"
    SetTestStateAborted
    exit 1
fi

# Verify XDP with each MTU size
for mtu in ${mtuSizes[@]}; do
    # Change MTU to Max on server
    LogMsg "Changing MTU on ${server}"
    change_mtu ${server} ${nicName} ${mtu}

    # Change MTU to Max on client
    LogMsg "Changing MTU on ${client}"
    change_mtu ${client} ${nicName} ${mtu}

    # packetSize = MTU - (IP Header[20] + ICMP Header[8])
    ping_test $((mtu-28))
    LogMsg "Successfully verified MTU ${mtu}"
done

# Verify failure to load XDP with MTU greater than max
LogMsg "Verify XDP with MTU greater than max"
change_mtu ${client} ${nicName} $((maxMtuSize+1))

LogMsg "Starting XDP Dump on ${client}"
# https://lore.kernel.org/lkml/1579558957-62496-3-git-send-email-haiyangz@microsoft.com/t/
LogMsg "XDP program cannot run with LRO (RSC) enabled, disable LRO before running XDP"
ssh ${client} "ethtool -K ${nicName} lro off"
# start XDP to check error catched
ssh ${client} "cd bpf-samples/xdpdump && timeout 10 ./xdpdump -i ${nicName}"
if [ $? -eq 0 ]; then
    LogMsg "Error: Current result does not match expected results"
    change_mtu ${client} ${nicName} ${defaultMtu}
    SetTestStateAborted
    exit 1
fi
LogMsg "Verified: Error caught by XDP for MTU greater than MAX MTU"

LogMsg "Changing MTU back to ${defaultMtu}"
change_mtu ${client} ${nicName} ${defaultMtu}
SetTestStateCompleted
LogMsg "*********INFO: XDP MTU Verification completed*********"
exit 0
