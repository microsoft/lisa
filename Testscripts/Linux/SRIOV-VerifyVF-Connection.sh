#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Description:
#   Basic SR-IOV test checks connectivity SR-IOV between two VMs
#   Steps:
#   1. Verify/install pciutils package
#   2. Using the lspci command, examine the NIC with SR-IOV support
#   3. Check network capability
#   4. Send a 1GB file from VM1 to VM2
# Note: This script can handle multiple SR-IOV interfaces
#
########################################################################
remote_user="root"
if [ ! -e sriov_constants.sh ]; then
    cp /${remote_user}/sriov_constants.sh .
fi

# Source SR-IOV_Utils.sh. This is the script that contains all the
# SR-IOV basic functions (checking drivers, checking VFs, assigning IPs)
. SR-IOV-Utils.sh || {
    echo "ERROR: unable to source SR-IOV_Utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Check if the SR-IOV driver is in use
VerifyVF
if [ $? -ne 0 ]; then
    LogErr "VF is not loaded! Make sure you are using compatible hardware"
    SetTestStateFailed
    exit 0
fi

if [ "$rescind_pci" = "yes" ]; then
    # call rescind function with param SRIOV
    if ! RescindPCI "SR-IOV"; then
        LogErr "Could not rescind pci device."
        SetTestStateFailed
        exit 0
    fi
fi

# Create an 1gb file to be sent from VM1 to VM2
Create1Gfile
if [ $? -ne 0 ]; then
    LogErr "Could not create the 1gb file on VM1!"
    SetTestStateFailed
    exit 0
fi

# Check if the VF count inside the VM is the same as the expected count
vf_count=$(find /sys/devices -name net -a -ipath '*vmbus*' | grep pci | wc -l)
if [ "$vf_count" -ne "$NIC_COUNT" ]; then
    LogErr "Expected VF count: $NIC_COUNT. Actual VF count: $vf_count"
    SetTestStateFailed
    exit 0
fi
UpdateSummary "Expected VF count: $NIC_COUNT. Actual VF count: $vf_count"

__iterator=1
__ip_iterator_1=1
__ip_iterator_2=2
# Ping and send file from VM1 to VM2
while [ $__iterator -le "$vf_count" ]; do
    # Extract VF_IP values
    ip_variable_name="VF_IP$__ip_iterator_1"
    static_IP_1="${!ip_variable_name}"
    ip_variable_name="VF_IP$__ip_iterator_2"
    static_IP_2="${!ip_variable_name}"

    synthetic_interface_vm_1=$(ip addr | grep $static_IP_1 | awk '{print $NF}')
    LogMsg  "Synthetic interface found: $synthetic_interface_vm_1"
    vf_interface_vm_1=$(find /sys/devices/* -name "*${synthetic_interface_vm_1}" | grep "pci" | sed 's/\// /g' | awk '{print $12}')
    LogMsg "Virtual function found: $vf_interface_vm_1"

    # Ping the remote host
    ping -c 11 "$static_IP_2" >/dev/null 2>&1
    if [ 0 -eq $? ]; then
        LogMsg "Successfully pinged $VF_IP2 through $synthetic_interface_vm_1"
    else
        LogErr "Unable to ping $VF_IP2 through $synthetic_interface_vm_1"
        SetTestStateFailed
        exit 0
    fi

    # Send 1GB file from VM1 to VM2 via eth1
    scp -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$output_file" "$remote_user"@"$static_IP_2":/tmp/"$output_file"
    if [ 0 -ne $? ]; then
        LogErr "Unable to send the file from VM1 to VM2 ($static_IP_2)"
        SetTestStateFailed
        exit 0
    else
        LogMsg "Successfully sent $output_file to $VF_IP2"
    fi

    tx_value=$(cat /sys/class/net/"${vf_interface_vm_1}"/statistics/tx_packets)
    LogMsg "TX value after sending the file: $tx_value"
    if [ "$tx_value" -lt 400000 ]; then
        LogErr "insufficient TX packets sent"
        SetTestStateFailed
        exit 0
    fi

    # Get the VF name from VM2
    cmd_to_send="ip addr | grep \"$static_IP_2\" | awk '{print \$NF}'"
    synthetic_interface_vm_2=$(ssh -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$static_IP_2" "$cmd_to_send")
    cmd_to_send="find /sys/devices/* -name "*${synthetic_interface_vm_2}" | grep pci | sed 's/\// /g' | awk '{print \$12}'"
    vf_interface_vm_2=$(ssh -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$static_IP_2" "$cmd_to_send")

    rx_value=$(ssh -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$static_IP_2" cat /sys/class/net/"${vf_interface_vm_2}"/statistics/rx_packets)
    LogMsg "RX value after sending the file: $rx_value"
    if [ "$rx_value" -lt 400000 ]; then
        LogErr "insufficient RX packets received"
        SetTestStateFailed
        exit 0
    fi
    UpdateSummary "Successfully sent file from VM1 to VM2 through $synthetic_interface_vm_1"

    __ip_iterator_1=$(($__ip_iterator_1 + 2))
    __ip_iterator_2=$(($__ip_iterator_2 + 2))
    : $((__iterator++))
done

LogMsg "Updating test case state to completed"
SetTestStateCompleted
exit 0