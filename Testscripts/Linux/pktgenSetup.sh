#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

packetCount=10000000
packetDropThreshold=90

function get_vf_name() {
        local ignoreIF=$(ip route | grep default | awk '{print $5}')
        local interfaces=$(ls /sys/class/net | grep -v lo | grep -v ${ignoreIF})
        local synthIFs=""
        local vfIFs=""
        local interface
        for interface in ${interfaces}; do
                # alternative is, but then must always know driver name
                # readlink -f /sys/class/net/<interface>/device/driver/
                local bus_addr=$(ethtool -i ${interface} | grep bus-info | awk '{print $2}')
                if [ -z "${bus_addr}" ]; then
                        synthIFs="${synthIFs} ${interface}"
                else
                        vfIFs="${vfIFs} ${interface}"
                fi
        done

        local vfIF
        local synthMAC=$(ip link show $nicName | grep ether | awk '{print $2}')
        for vfIF in ${vfIFs}; do
                local vfMAC=$(ip link show ${vfIF} | grep ether | awk '{print $2}')
                # single = is posix compliant
                if [ "${synthMAC}" = "${vfMAC}" ]; then
                        echo "${vfIF}"
                        break
                fi
        done
}

function calculate_packets_drop(){
        local vfName=$1
        local synthDrop=0
        IFS=$'\n' read -r -d '' -a xdp_packet_array < <(ethtool -S $nicName | grep 'xdp' | cut -d':' -f2)
        for i in "${xdp_packet_array[@]}";
        do
                synthDrop=$((synthDrop+i))
        done
        vfDrop=$(ethtool -S $vfName | grep rx_xdp_drop | cut -d':' -f2)
        if [ $? -ne 0 ]; then
                echo "$((synthDrop))"
        else
                echo "$((vfDrop + synthDrop))"
        fi

}

function download_pktgen_scripts(){
        local ip=$1
        local dir=$2
        if [ "${core}" = "multi" ];then
                ssh $ip "wget https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/plain/samples/pktgen/pktgen_sample05_flow_per_thread.sh?h=v5.7.8 -O ${dir}/pktgen_sample.sh"
        else
                ssh $ip "wget https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/plain/samples/pktgen/pktgen_sample01_simple.sh?h=v5.7.8 -O ${dir}/pktgen_sample.sh"
        fi
        ssh $ip "wget https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/plain/samples/pktgen/functions.sh?h=v5.7.8 -O ${dir}/functions.sh"
        ssh $ip "wget https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/plain/samples/pktgen/parameters.sh?h=v5.7.8 -O ${dir}/parameters.sh"
        ssh $ip "chmod +x ${dir}/*.sh"
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
download_pktgen_scripts ${server} ${pktgenDir}

vfName=$(get_vf_name)
if [ -z "${vfName}" ]; then
        LogWarn "VF Name is not detected. Please check vm configuration."
fi
# Store current xdp drop queue variables
pakcetDropBefore=$(calculate_packets_drop $vfName)
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
pakcetDropAfter=$(calculate_packets_drop $vfName)

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
