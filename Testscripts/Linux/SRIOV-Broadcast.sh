#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Description:
#   Basic SR-IOV test that checks if VF can send and receive broadcast packets
# Steps:
#    Use ping for testing & tcpdump to check if the packets were received
#    On the 2nd VM – tcpdump -i eth1 -c 10 ip proto \\icmp > out.client
#    On the TEST VM – ping -b $broadcastAddress -c 13 &
#    On the 2nd VM – cat out.client | grep $broadcastAddress
#    If $?=0 test passed!
##############################################################################

function Execute_Validate_Remote_Command(){
    cmd_to_run=$1
    ssh -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$VF_IP2" $cmd_to_run
    if [ $? -ne 0 ]; then
        LogErr "Could not run the command '${cmd_to_run}' on VM2"
        SetTestStateAborted
        exit 0
    fi
}
remote_user="root"
cp /${remote_user}/sriov_constants.sh .
# Source utils.sh
. SR-IOV-Utils.sh || {
    echo "unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

broadcastAddress=$(ip a s dev eth1 | awk '/inet / {print $4}')
ping -b $broadcastAddress -c 13 &
if [ $? -ne 0 ]; then
    LogErr "Could not ping to broadcast address on VM1 (VF_IP: ${VF_IP1})"
    SetTestStateFailed
fi

# Configure VM2
Execute_Validate_Remote_Command "tcpdump -i eth1 -c 10 ip proto \\\\icmp > out.client"
Execute_Validate_Remote_Command "cat out.client | grep $broadcastAddress"

LogMsg "VM2 successfully received the packets sent to the broadcast address"
SetTestStateCompleted
exit 0
