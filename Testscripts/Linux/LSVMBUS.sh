#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

tokens=("Operating system shutdown" "Time Synchronization" "Heartbeat"
        "Data Exchange" "mouse" "keyboard"
        "Synthetic network adapter" "Synthetic SCSI Controller")
optional_tokens=("Guest services" "Dynamic Memory" )
numa_node=$(lscpu | grep -i "numa node" | grep -i cpu | wc -l)
declare -a network_numa
declare -a scsi_numa

# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

GetDistro
case $DISTRO in
    redhat_5|centos_5*)
    LogMsg "Info: RedHat/CentOS 5.x is not supported."
    SetTestStateSkipped
    exit 0
    ;;
esac

if [[ "$DISTRO" =~ "redhat" ]] || [[ "$DISTRO" =~ "centos" ]] || [[ "$DISTRO" =~ "almalinux" ]]; then
    if ! rpm -q hyperv-tools; then
        yum install -y hyperv-tools
    fi
fi

function judge_channel_count {
    prefix=$1
    index=$2
    expected_channel_count=$3
    for (( i = 1 ; i <= $index ; i++ )); do
        LogMsg "==================The $i $prefix=================="
        temp="$prefix$i"
        counter=${!temp}
        LogMsg "Expected for channels count of $temp: ${expected_channel_count} and actual: $counter."
        if [ "$counter" != "$expected_channel_count" ]; then
            SetTestStateFailed
            exit 0
        fi
    done
}

function judge_numa_node {
    prefix=$1
    index=$2
    shift 2
    numa_array=("$@")
    seen=()
    for i in "${numa_array[@]}"; do
        if [ -z "${seen[i]}" ]; then
            seen[i]=1
        fi
    done
    if [[ "$index" -ge "$numa_node" ]]; then
        # when count of channels >= numa nodes
        # the length of numa nodes collected from lsvmbus should equal to actual count of numa nodes
        if [[ "${#seen[@]}" -eq "$numa_node" ]]; then
            LogMsg "Channels of $prefix spreads into different numa node properly."
        else
            LogErr "Channels of $prefix doesn't spread into different numa node properly."
            SetTestStateFailed
            exit 0
        fi
    else
        # when count of channels < numa nodes
        # the length of numa nodes collected from lsvmbus should equal to count of channels
        if [[ "${#seen[@]}" -eq "$index" ]]; then
            LogMsg "Channels of n$prefix spreads into different numa node properly."
        else
            LogErr "Channels of $prefix doesn't spread into different numa node properly."
            SetTestStateFailed
            exit 0
        fi
    fi
}
#######################################################################
#
# Main script body
#
#######################################################################
VCPU=$(nproc)
LogMsg "Number of CPUs detected on VM: $VCPU"

# check if lsvmbus exists, or the running kernel does not match installed version of linux-tools
check_lsvmbus
lsvmbus_path=$(which lsvmbus)

GetGuestGeneration
if [ "$os_GENERATION" -eq "1" ]; then
    tokens+=("Synthetic IDE Controller")
fi

for token in "${tokens[@]}"; do
    if ! $lsvmbus_path | grep "$token"; then
        LogErr "$token not found in lsvmbus information."
        SetTestStateFailed
        exit 0
    fi
done
for optional_token in "${optional_tokens[@]}"; do
    if ! $lsvmbus_path | grep "$optional_token"; then
        LogMsg "INFO: $optional_token not found in lsvmbus information."
    fi
done

msg="Info: All VMBus device IDs have been found."
LogMsg "$msg"

# SECOND TEST CASE
# install bc tool if not exist
if ! which bc; then
    update_repos
    install_package bc
fi

$lsvmbus_path -vvv > lsvmbus.log

# the cpu count that attached to the network driver is MIN(the number of vCPUs, 8).
if [ "$VCPU" -gt 8 ];then
    expected_network_counter=8
else
    expected_network_counter=$VCPU
fi

if [ "$VCPU" -gt $((64*4)) ];then
    expected_scsi_counter=64
else
    expected_scsi_counter=$(bc <<<"scale=2;$VCPU/4")
    if ! [[ "$expected_scsi_counter" =~ \.00 ]]; then
        # In this case we have a float number that needs to be rounded up.
        # For example with 6 cores, scsi controller is spread on 2 cores.
        expected_scsi_counter=$(bc <<<"("$expected_scsi_counter"+1)/1")
    fi
    # normalizing the number to integer
    expected_scsi_counter=${expected_scsi_counter%.*}
fi

network_index=0
scsi_index=0
while IFS='' read -r line || [[ -n "$line" ]]; do
    if [[ $line =~ "VMBUS ID" ]]; then
        token=""
    fi
    if [[ $line =~ "Synthetic network adapter" ]]; then
        ((network_index++))
        export network_counter_$network_index=0
        token="adapter"
    fi

    if [[ $line =~ "Synthetic SCSI Controller" ]]; then
        ((scsi_index++))
        export scsi_counter_$scsi_index=0
        token="controller"
    fi

    if [[ -n $token ]] && [[ $line =~ "/sys/bus/vmbus/devices" ]]; then
        # Sysfs path: /sys/bus/vmbus/devices/f8b3781b-1e82-4818-a1c3-63d806ec15bb
        # get sysfs path, then get numa node
        # cat /sys/bus/vmbus/devices/f8b3781b-1e82-4818-a1c3-63d806ec15bb/numa_node
        IFS=':' read -ra array <<< "$line"
        if [[ $token == "adapter" ]]; then
            network_numa[network_index-1]=$(cat ${array[-1]}/numa_node)
        elif [[ $token == "controller" ]]; then
            scsi_numa[scsi_index-1]=$(cat ${array[-1]}/numa_node)
        fi
    fi

    if [[ -n $token ]] && [[ $line =~ "target_cpu" ]]; then
        # one line for Rel_ID=21, target_cpu=11 means one channel
        if [[ $token == "adapter" ]]; then
            ((network_counter_$network_index++))
        elif [[ $token == "controller" ]]; then
            ((scsi_counter_$scsi_index++))
        fi
    fi
done < "lsvmbus.log"

judge_channel_count "network_counter_" $network_index $expected_network_counter
judge_channel_count "scsi_counter_" $scsi_index $expected_scsi_counter

judge_numa_node "network adapter" $network_index "${network_numa[@]}"
judge_numa_node "scsi controller" $scsi_index "${scsi_numa[@]}"

SetTestStateCompleted
exit 0
