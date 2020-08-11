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
lsvmbus_path=$(which lsvmbus)
if [[ -z "$lsvmbus_path" ]] || ! $lsvmbus_path > /dev/null 2>&1; then
    install_package wget
    wget https://raw.githubusercontent.com/torvalds/linux/master/tools/hv/lsvmbus
    chmod +x lsvmbus
    if [[ "$DISTRO" =~ "coreos" ]]; then
        export PATH=$PATH:/usr/share/oem/python/bin/
        lsvmbus_path="./lsvmbus"
    else
        mv lsvmbus /usr/sbin
        lsvmbus_path=$(which lsvmbus)
    fi
fi

if [ -z "$lsvmbus_path" ]; then
    LogErr "lsvmbus tool not found!"
    SetTestStateFailed
    exit 0
fi

GetGuestGeneration
if [ "$os_GENERATION" -eq "1" ]; then
    tokens+=("Synthetic IDE Controller")
fi

# lsvmbus requires python
which python || [ -f /usr/libexec/platform-python ] && ln -s /usr/libexec/platform-python /sbin/python || which python3 && ln -s $(which python3) /sbin/python
if ! which python; then
    update_repos
    install_package python
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
TIMESTAMP=$(date +%Y%m%d-%H%M)
$lsvmbus_path -vvv > "lsvmbus_$TIMESTAMP.log"
net_adapter_index=0
network_counter=0
scsi_index=0
scsi_counter=0

declare -A ADAPTER_DICT=()
declare -A SCSI_DICT=()

while IFS='' read -r line || [[ -n "$line" ]]; do
    if [[ "$line" =~ "VMBUS ID" ]]; then
        token=""
    fi

    if [[ "$line" =~ "Synthetic SCSI Controller" ]]; then
        ((scsi_index++))
        token="controller"
    fi

    if [[ "$line" =~ "Synthetic network adapter" ]]; then
        ((net_adapter_index++))
        token="adapter"
    fi

    if [[ "$line" == "" ]]; then
        token=""
        network_counter=0
        scsi_counter=0
    fi

    if [[ "$token" == "adapter" ]] && [[ "$line" =~ "target_cpu" ]]; then
        ADAPTER_DICT["adapter$net_adapter_index"]=$((++network_counter))
    fi

    if [[ "$token" == "controller" ]] && [[ "$line" =~ "target_cpu" ]]; then
        SCSI_DICT["scsi$scsi_index"]=$((++scsi_counter))
    fi
done < "lsvmbus_$TIMESTAMP.log"


# the cpu count that attached to the network driver is MIN(the number of vCPUs, 8).
if [ "$VCPU" -gt 8 ];then
    expected_network_counter=8
else
    expected_network_counter=$VCPU
fi

# Default: the cpu count that attached to the SCSI driver is MIN(the number of vCPUs/4, 64).
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

testfail=0
for adapter in "${!ADAPTER_DICT[@]}"; do
    if [ "${ADAPTER_DICT[$adapter]}" != "$expected_network_counter" ]; then
        error_msg="Error: values are wrong. Expected for network adapter $adapter channels: $expected_network_counter and actual: ${ADAPTER_DICT[$adapter]}"
        LogErr "$error_msg"
        UpdateSummary "$error_msg"
        testfail=1
    else
        UpdateSummary "Expected for network adapter $adapter channels: $expected_network_counter and actual: ${ADAPTER_DICT[$adapter]}"
    fi
done

for scsi in "${!SCSI_DICT[@]}"; do
    if [ "${SCSI_DICT[$scsi]}" != "$expected_scsi_counter" ]; then
        error_msg="Error: values are wrong. Expected for scsi $scsi channels: $expected_scsi_counter and actual: ${SCSI_DICT[$scsi]}"
        LogErr "$error_msg"
        UpdateSummary "$error_msg"
        testfail=1
    else
        UpdateSummary "Expected for scsi $scsi channels: $expected_scsi_counter and actual: ${SCSI_DICT[$scsi]}"
    fi
done


if [ "$testfail" == 1 ]; then
    error_msg="scsi channels or network adapter channels are NOT expected, test fail."
    LogErr "$error_msg"
    UpdateSummary "$error_msg"
    SetTestStateFailed
    exit 0
fi

SetTestStateCompleted
exit 0
