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

VCPU=$(nproc)
LogMsg "Number of CPUs detected from this VM: $VCPU"

# check if lsvmbus exists
lsvmbus_path=$(which lsvmbus)
if [ -z "$lsvmbus_path" ]; then
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

# python required for lsvmbus
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

# SECOND TEST CASE
$lsvmbus_path -vvv > lsvmbus.log

#Check number of NICs on VM
nics=$( grep -o "Synthetic network adapter" lsvmbus.log | wc -l)
if [ "$nics" -gt 1 ]; then
  LogMsg "Counting the cores spread only for the first NIC.."
  UpdateSummary "Counting the cores spread only for the first NIC..."
  sed -i ':a;N;$!ba;s/Synthetic network adapter/ignored adapter/2' lsvmbus.log && \
  sed -i '/ignored adapter/,$d' lsvmbus.log
fi

#Check number of SCSI Controllers on VM
scsiAdapters=$( grep -o "Synthetic SCSI Controller" lsvmbus.log | wc -l)
if [ "$scsiAdapters" -gt 1 ]; then
  LogMsg "Counting the cores spread only for the first SCSI Adapter.."
  UpdateSummary "Counting the cores spread only for the first SCSI Adapter..."
  sed -i ':a;N;$!ba;s/Synthetic SCSI Controller/ignored controller/2' lsvmbus.log && \
  sed -i '/ignored controller/,$d' lsvmbus.log
fi

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

# the cpu count that attached to the network driver is MIN(the number of vCPUs, 8).
if [ "$VCPU" -gt 8 ];then
    expected_netwok_counter=8
else
    expected_netwok_counter=$VCPU
fi

# the cpu count that attached to the SCSI driver is MIN(the number of vCPUs/4, 64).
if [ "$VCPU" -gt 64 ];then
    expected_scsi_counter=64
else
    expected_scsi_counter=$(expr "$VCPU" / 4)
fi

if [ "$network_counter" != "$expected_netwok_counter" ] && [ "$scsi_counter" != "$expected_scsi_counter" ]; then
    error_msg="Error: values are wrong. Expected for network adapter: $VCPU and actual: $network_counter;
    expected for scsi controller: ${expected_scsi_counter}, actual: $scsi_counter."
    LogErr "$error_msg"
    SetTestStateFailed
    exit 0
fi

LogMsg "Network driver is spread on all $network_counter cores as expected."
LogMsg "Storage driver is spread on all $scsi_counter cores as expected."
LogMsg "Info: All VMBus device IDs have been found."
SetTestStateCompleted
exit 0
