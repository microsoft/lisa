#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

tokens=("Operating system shutdown" "Time Synchronization" "Heartbeat"
        "Data Exchange" "mouse" "keyboard"
        "Synthetic network adapter" "Synthetic SCSI Controller")
optional_tokens=("Guest services" "Dynamic Memory" )

network_counter=0
scsi_counter=0

# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit
LogMsg "VM Size: $VM_Size"

GetDistro
case $DISTRO in
    redhat_5|centos_5*)
    LogMsg "Info: RedHat/CentOS 5.x is not supported."
    SetTestStateSkipped
    exit 0
    ;;
esac

if [[ "$DISTRO" =~ "redhat" ]] || [[ "$DISTRO" =~ "centos" ]]; then
    if ! rpm -q hyperv-tools; then
        yum install -y hyperv-tools
    fi
fi

#######################################################################
#
# Main script body
#
#######################################################################
VCPU=$(nproc)
LogMsg "Number of CPUs detected on VM: $VCPU"

# check if lsvmbus exists, or the running kernel does not match installed version of linux-tools
Check_lsvmbus
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
UpdateSummary "$msg"

# SECOND TEST CASE
# install bc tool if not exist
if ! which bc; then
    update_repos
    install_package bc
fi

$lsvmbus_path -vvv > lsvmbus.log

# Check number of NICs on VM
nics=$( grep -o "Synthetic network adapter" lsvmbus.log | wc -l)
if [ "$nics" -gt 1 ]; then
    LogMsg "Counting the cores spread only for the first NIC..."
    sed -i ':a;N;$!ba;s/Synthetic network adapter/ignored adapter/2' lsvmbus.log && \
    sed -i '/ignored adapter/,/^$/d' lsvmbus.log
fi

# Check number of SCSI Controllers on VM
scsiAdapters=$( grep -o "Synthetic SCSI Controller" lsvmbus.log | wc -l)
if [ "$scsiAdapters" -gt 1 ]; then
    LogMsg "Counting the cores spread only for the first SCSI Adapter..."
    sed -i ':a;N;$!ba;s/Synthetic SCSI Controller/ignored controller/2' lsvmbus.log && \
    sed -i '/ignored controller/,/^$/d' lsvmbus.log
fi

while IFS='' read -r line || [[ -n "$line" ]]; do
    if [[ $line =~ "VMBUS ID" ]]; then
        token=""
    fi
    if [[ $line =~ "Synthetic network adapter" ]]; then
        token="adapter"
    fi

    if [[ $line =~ "Synthetic SCSI Controller" ]]; then
        token="controller"
    fi

    if [[ -n $token ]] && [[ $line =~ "target_cpu" ]]; then
        if [[ $token == "adapter" ]]; then
            ((network_counter++))
        elif [[ $token == "controller" ]]; then
            ((scsi_counter++))
        fi
    fi
done < "lsvmbus.log"

# the cpu count that attached to the network driver is MIN(the number of vCPUs, 8).
if [ "$VCPU" -gt 8 ];then
    expected_network_counter=8
else
    expected_network_counter=$VCPU
fi

case $VM_Size in
    # If Lv2, the cpu count that attached to the SCSI driver is MIN(the number of vCPUs, 64).
    *Standard_L*s_v2*)
        if [ "$VCPU" -gt 64 ];then
            expected_scsi_counter=64
        else
            expected_scsi_counter=$VCPU
        fi
    ;;
    # Default: the cpu count that attached to the SCSI driver is MIN(the number of vCPUs/4, 64).
    *)
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
    ;;
esac

if [ "$network_counter" != "$expected_network_counter" ] || [ "$scsi_counter" != "$expected_scsi_counter" ]; then
    error_msg="Error: values are wrong. Expected for network adapter: ${expected_network_counter} and actual: $network_counter;
    expected for scsi controller: ${expected_scsi_counter}, actual: $scsi_counter."
    LogErr "$error_msg"
    UpdateSummary "$error_msg"
    SetTestStateFailed
    exit 0
fi

msg="Network driver is spread on all $network_counter cores as expected ${expected_network_counter} cores."
LogMsg "$msg"
UpdateSummary "$msg"

msg="Storage driver is spread on all $scsi_counter cores as expected ${expected_scsi_counter} cores."
LogMsg "$msg"
UpdateSummary "$msg"

SetTestStateCompleted
exit 0
