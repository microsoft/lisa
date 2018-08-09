#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

tokens=("Operating system shutdown" "Time Synchronization" "Heartbeat"
        "Data Exchange" "mouse" "keyboard"
        "Synthetic network adapter" "Synthetic SCSI Controller")
optional_tokens=("Guest services" "Dynamic Memory" )

network_counter=0
scsi_counter=0
#######################################################################
#
# Main script body
#
#######################################################################
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

if [[ "$DISTRO" =~ "redhat" ]] || [[ "$DISTRO" =~ "centos" ]]; then
    if ! rpm -q hyperv-tools; then
        yum install -y hyperv-tools
    fi
fi

# check if lsvmbus exists
lsvmbus_path=$(which lsvmbus)
if [ -z "$lsvmbus_path" ]; then
    LogMsg "Error: lsvmbus tool not found!"
    SetTestStateFailed
    exit 0
fi

GetGuestGeneration
if [ "$os_GENERATION" -eq "1" ]; then
    tokens+=("Synthetic IDE Controller")
fi

for token in "${tokens[@]}"; do
    if ! $lsvmbus_path | grep "$token"; then
        LogMsg "Error: $token not found in lsvmbus information."
        SetTestStateFailed
        exit 0
    fi
done
for optional_token in "${optional_tokens[@]}"; do
    if ! $lsvmbus_path | grep "$token"; then
        LogMsg "INFO: $token not found in lsvmbus information."
    fi
done

# SECOND TEST CASE
$lsvmbus_path -vvv >> lsvmbus.log

while IFS='' read -r line || [[ -n "$line" ]]; do
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
expected_scsi_counter=$(expr $VCPU / 4)

if [ "$network_counter" != "$VCPU" ] && [ "$scsi_counter" != "$expected_scsi_counter" ]; then
    error_msg="Error: values are wrong. Expected for network adapter: $VCPU and actual: $network_counter;
    expected for scsi controller: ${expected_scsi_counter}, actual: $scsi_counter."
    LogMsg "$error_msg"
    SetTestStateFailed
    exit 0
fi

LogMsg "Network driver is spread on all $network_counter cores as expected."
LogMsg "Storage driver is spread on all $scsi_counter cores as expected."
LogMsg "Info: All VMBus device IDs have been found."
SetTestStateCompleted
exit 0
