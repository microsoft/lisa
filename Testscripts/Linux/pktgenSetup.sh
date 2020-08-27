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

# Source utils.sh
. ${XDPUTIL_FILE} || {
    echo "ERROR: unable to source ${XDPUTIL_FILE}!"
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
                exit 0
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

vfName=$(get_vf_name ${nicName})
if [ -z "${vfName}" ]; then
        LogErr "VF Name is not detected. Please check vm configuration."
fi
# Store current xdp drop queue variables
pakcetDropBefore=$(calculate_packets_drop $nicName)
# start xdpdump with drop
xdpdumpCommand="cd bpf-samples/xdpdump && ./xdpdump -i ${nicName} > ~/xdpdumpout.txt"
LogMsg "Starting xdpdump on ${client} with command: ${xdpdumpCommand}"
ssh -f ${client} "sh -c '${xdpdumpCommand}'"


# Start pktgen application
clientSecondMAC=$(ip link show $nicName | grep ether | awk '{print $2}')
if [ "${core}" = "single" ];then
        LogMsg "Starting pktgen on server: cd ${pktgenDir} && ./pktgen_sample.sh -i ${nicName} -m ${clientSecondMAC} -d ${clientSecondIP} -v -n100000"
        ssh ${server} "modprobe pktgen; lsmod | grep pktgen"
        result=$(ssh ${server} "cd ${pktgenDir} && ./pktgen_sample.sh -i ${nicName} -m ${clientSecondMAC} -d ${clientSecondIP} -v -n${packetCount}")
else
        LogMsg "Starting pktgen on server: cd ${pktgenDir} && ./pktgen_sample.sh -i ${nicName} -m ${clientSecondMAC} -d ${clientSecondIP} -v -n${packetCount} -t8"
        ssh ${server} "modprobe pktgen; lsmod | grep pktgen"
        result=$(ssh ${server} "cd ${pktgenDir} && ./pktgen_sample.sh -i ${nicName} -m ${clientSecondMAC} -d ${clientSecondIP} -v -n${packetCount} -t8")
fi
sleep 10
pps=$(echo $result | grep -oh '[0-9]*pps' | cut -d'p' -f 1)
LogMsg "PPS: $pps"
# Get drop packet numbers
pakcetDropAfter=$(calculate_packets_drop $nicName)

LogMsg "Before Drop: $pakcetDropBefore After Drop:$pakcetDropAfter "
packetsDropped=$((pakcetDropAfter - pakcetDropBefore))
LogMsg "Pakcets dropped: $packetsDropped"
dropLimit=$(( packetCount*packetDropThreshold/100 ))
if [ $packetsDropped -lt $dropLimit ]; then
        LogErr "receiver did not receive packets."
        SetTestStateAborted
fi
ssh ${client} "killall xdpdump"
if [ $pps -ge 1000000 ]; then
        LogMsg "pps is greater than 1 Mpps"
        SetTestStateCompleted
else
        LogErr "pps is lower than 1 Mpps"
        SetTestStateFailed
fi
