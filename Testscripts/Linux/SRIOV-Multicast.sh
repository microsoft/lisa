#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Description:
#   Basic SR-IOV test that checks if VF can send and receive multicast packets
#   On the 2nd VM: ping -I eth1 224.0.0.1 -c 11 > out.client &
#   On the TEST VM: ping -I eth1 224.0.0.1 -c 11 > out.client
#   Check results:
#   On the TEST VM: cat out.client | grep 0%
#   On the 2nd VM: cat out.client | grep 0%
#   If both have 0% packet loss, test passed
################################################################################

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

# Configure VM1
ip link set dev eth1 allmulticast on
if [ $? -ne 0 ]; then
    LogErr "ERROR: Could not enable ALLMULTI on VM1"
    SetTestStateAborted
    exit 0
fi

# Configure VM2
Execute_Validate_Remote_Command "ip link set dev eth1 allmulticast on"
Execute_Validate_Remote_Command "echo '1' > /proc/sys/net/ipv4/ip_forward"
Execute_Validate_Remote_Command "ip route add 224.0.0.0/4 dev eth1"
Execute_Validate_Remote_Command "echo '0' > /proc/sys/net/ipv4/icmp_echo_ignore_broadcasts"
Execute_Validate_Remote_Command "ping -I eth1 224.0.0.1 -c 29 > out.client &"

ping -I eth1 224.0.0.1 -c 11 > out.client
if [ $? -ne 0 ]; then
    LogErr "Could not start ping on VM1 (VF_IP: ${VF_IP1})"
    SetTestStateFailed
    exit 0
fi
LogMsg "INFO: Ping was started on both VMs. Results will be checked in a few seconds"
 
# Check results on VM1- Summary must show a 0% loss of packets
multicastSummary=$(cat out.client | grep 0%)
if [ $? -ne 0 ]; then
    LogErr "VM1 shows that packets were lost!"
    LogErr "${multicastSummary}"
    SetTestStateFailed
    exit 0
fi

# Wait 20 seconds to make sure ping ended on VM2 & check results there
sleep 20
Execute_Validate_Remote_Command "cat out.client | grep 0%"

LogMsg "Multicast summary"
LogMsg "${multicastSummary}"
LogMsg "Multicast packets were successfully sent, 0% loss"
SetTestStateCompleted
exit 0
