#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
#   Disable VF, verify SR-IOV Failover is working
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
# Create an 1gb file to be sent from VM1 to VM2
Create1Gfile
if [ $? -ne 0 ]; then
    LogErr "Could not create the 1gb file on VM1!"
    SetTestStateFailed
    exit 0
fi

# Check if the VF count inside the VM is the same as the expected count
vf_count=$(get_vf_count)
if [ "$vf_count" -ne "$NIC_COUNT" ]; then
    LogErr "Expected VF count: $NIC_COUNT. Actual VF count: $vf_count"
    SetTestStateFailed
    exit 0
fi
UpdateSummary "Expected VF count: $NIC_COUNT. Actual VF count: $vf_count"

# Extract VF name
synthetic_interface=$(ip addr | grep "$VF_IP1" | awk '{print $NF}')
LogMsg  "Synthetic interface found: $synthetic_interface"
if [[ $DISTRO_VERSION =~ ^6\. ]]; then
    synthetic_MAC=$(ip link show ${synthetic_interface} | grep ether | awk '{print $2}')
    vf_interface=$(grep -il ${synthetic_MAC} /sys/class/net/*/address | grep -v $synthetic_interface | sed 's/\// /g' | awk '{print $4}')
else
    if [[ -d /sys/firmware/efi ]]; then
    # This is the case of VM gen 2
        vf_interface=$(find /sys/devices/* -name "*${synthetic_interface}" | grep pci | sed 's/\// /g' | awk '{print $11}')
    else
    # VM gen 1 case
        vf_interface=$(find /sys/devices/* -name "*${synthetic_interface}" | grep pci | sed 's/\// /g' | awk '{print $12}')
    fi
fi
LogMsg "Virtual function found: $vf_interface"

# Put VF down
ip link set dev "$vf_interface" down
ping -c 11 "$VF_IP2" >/dev/null 2>&1
if [ 0 -eq $? ]; then
    LogMsg "Successfully pinged $VF_IP2 with VF down"
else
    LogErr "Unable to ping $VF_IP2 with VF down"
    SetTestStateFailed
    exit 0
fi
# Send 1GB file from VM1 to VM2 via synthetic interface
scp -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$output_file" "$remote_user"@"$VF_IP2":/tmp/"$output_file"
if [ 0 -ne $? ]; then
    LogErr "Unable to send the file from VM1 to VM2 ($VF_IP2)"
    SetTestStateFailed
    exit 0
else
    LogMsg "Successfully sent $output_file to $VF_IP2"
fi
# Get TX value for synthetic interface after sending the file
tx_value=$(cat /sys/class/net/"${synthetic_interface}"/statistics/tx_packets)
LogMsg "TX value after sending the file: $tx_value"
if [ "$tx_value" -lt 10000 ]; then
    LogErr "Insufficient TX packets sent on ${synthetic_interface}"
    SetTestStateFailed
    exit 0
fi

# Put VF up
ip link set dev "$vf_interface" up
ping -c 11 "$VF_IP2" >/dev/null 2>&1
if [ 0 -ne $? ]; then
    LogErr "Unable to ping $VF_IP2 with VF down"
    SetTestStateFailed
    exit 0
fi
# Send 1GB file from VM1 to VM2 via VF
scp -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$output_file" "$remote_user"@"$VF_IP2":/tmp/"$output_file"
if [ 0 -ne $? ]; then
    LogErr "Unable to send the file from VM1 to VM2 ($VF_IP2)"
    SetTestStateFailed
    exit 0
else
    LogMsg "Successfully sent $output_file to $VF_IP2"
fi
# Get TX value for VF after sending the file
tx_value=$(cat /sys/class/net/"${vf_interface}"/statistics/tx_packets)
LogMsg "TX value after sending the file: $tx_value"
if [ "$tx_value" -lt 10000 ]; then
    LogErr "Insufficient TX packets sent on ${vf_interface}"
    SetTestStateFailed
    exit 0
fi

UpdateSummary "Successfully disabled and enabled VF"
SetTestStateCompleted
exit 0
