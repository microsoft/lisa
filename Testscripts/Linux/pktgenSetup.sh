#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

packetCount=10000000
packetDropThreshold=90

UTIL_FILE="./utils.sh"

# Source utils.sh
. ${UTIL_FILE} || {
    echo "ERROR: unable to source ${UTIL_FILE}!"
    echo "TestAborted" > state.txt
    exit 0
}

XDPUTIL_FILE="./XDPUtils.sh"

# Source XDPUtils.sh
. ${XDPUTIL_FILE} || {
    LogMsg "ERROR: unable to source ${XDPUTIL_FILE}!"
    SetTestStateAborted
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

# Build xdpdump with DROP Config
LogMsg "Build XDPDump with PERF_DROP flags"
ssh ${client} "cd bpf-samples/xdpdump && make clean && CFLAGS='-D __PERF_DROP__ -D __PERF__ -I../libbpf/src/root/usr/include' make"
check_exit_status "Building xdpdump with config"

# Configure pktgen application
pktgenDir=~/pktgen
ssh ${server} "mkdir -p ${pktgenDir}"
download_pktgen_scripts ${server} ${pktgenDir} ${cores}


vfName=$(get_vf_name "${nicName}")

if [ -z "${vfName}" ]; then
    LogErr "VF Name is not detected. Please check vm configuration."
fi
# Store current xdp drop queue variables
pakcetDropBefore=$(calculate_packets_drop $nicName)
# https://lore.kernel.org/lkml/1579558957-62496-3-git-send-email-haiyangz@microsoft.com/t/
LogMsg "XDP program cannot run with LRO (RSC) enabled, disable LRO before running XDP"
ssh ${client} "ethtool -K ${nicName} lro off"
# start xdpdump with drop
start_xdpdump ${client} ${nicName}

# Start pktgen application
clientSecondMAC=$(ip link show $nicName | grep ether | awk '{print $2}')
LogMsg "Starting pktgen on ${server}"
start_pktgen ${server} ${cores} ${pktgenDir} ${nicName} ${clientSecondMAC} ${clientSecondIP} ${packetCount}
sleep 5
pps=$(echo $pktgenResult | grep -oh '[0-9]*pps' | cut -d'p' -f 1)
if [ $? -ne 0 ]; then
    LogErr "Problem in running pktgen. No PPS found. Please check logs."
    SetTestStateAborted
    exit 0
fi
LogMsg "PPS: $pps"
# Get drop packet numbers
pakcetDropAfter=$(calculate_packets_drop $nicName)

LogMsg "Before Drop: $pakcetDropBefore After Drop:$pakcetDropAfter "
packetsDropped=$((pakcetDropAfter - pakcetDropBefore))
LogMsg "Pakcets dropped: $packetsDropped"
dropLimit=$(( packetCount*packetDropThreshold/100 ))
if [ $packetsDropped -lt $dropLimit ]; then
    LogErr "receiver did not receive enough packets. Receiver received ${packetsDropped} which is lower than threshold" \
            "of ${packetDropThreshold}% of ${packetCount}. Please check logs"
    SetTestStateFailed
    exit 1
fi
ssh ${client} "killall xdpdump"
if [ $pps -ge 1000000 ]; then
    LogMsg "pps is greater than 1 Mpps"
    echo "test_type,sender_pps,packets_sent,packets_received" > report.csv
    echo "${cores},${pps},${packetCount},${packetsDropped}" >> report.csv
    SetTestStateCompleted
    exit 0
else
    LogErr "pps is lower than 1 Mpps"
    SetTestStateFailed
    exit 1
fi
