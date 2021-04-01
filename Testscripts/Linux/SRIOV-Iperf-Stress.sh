#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
#   This SR-IOV test will run iPerf3 for 30 minutes and checks
# if network connectivity is lost at any point
#
########################################################################
remote_user="root"
if [ ! -e sriov_constants.sh ]; then
    cp /${remote_user}/sriov_constants.sh .
fi
export PATH="/usr/local/bin:${PATH}"
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

# Check if the VF count inside the VM is the same as the expected count
vf_count=$(get_vf_count)
if [ "$vf_count" -ne "$NIC_COUNT" ]; then
    LogErr "Expected VF count: $NIC_COUNT. Actual VF count: $vf_count"
    SetTestStateFailed
    exit 0
fi
UpdateSummary "Expected VF count: $NIC_COUNT. Actual VF count: $vf_count"

# Start iPerf server on dependency VM
ssh -i "/$remote_user"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$VF_IP2" 'iperf3 -s &> perfResults.log &'
if [ $? -ne 0 ]; then
    LogErr "Could not start iPerf3 on VM2 (VF_IP: ${VF_IP2})"
    SetTestStateFailed
    exit 0
fi

# Start iPerf client
iperf3 -t 1800 -c "${VF_IP2}" --logfile perfResults.log
if [ $? -ne 0 ]; then
    LogErr "Could not start iPerf3 on VM1 (VF_IP: ${VF_IP1})"
    SetTestStateFailed
    exit 0
fi

# Check for errors
if [ ! -e perfResults.log ]; then
    LogErr "iPerf3 didn't run!"
    SetTestStateFailed
    exit 0
fi

iperf_errors=$(cat perfResults.log | grep -i error)
if [ $? -eq 0 ]; then
    LogErr "iPerf3 had errors while running"
    LogErr "$iperf_errors"
    SetTestStateFailed
    exit 0
fi

# Get the throughput
throughput=$(tail -4 perfResults.log | head -1 | awk '{print $7}')
UpdateSummary "iPerf3 throughput is $throughput gbps"

# Check the connection again
ping -c 11 "${VF_IP2}" > pingResults.log
if [ $? -ne 0 ]; then
    LogErr "Could not ping from VM1 to VM2 after iPerf3 finished the run"
    SetTestStateFailed
    exit 0
fi
cat pingResults.log | grep " 0%"
if [ $? -ne 0 ]; then
    LogErr "Ping shows that packets were lost between VM1 and VM"
    SetTestStateFailed
    exit 0
fi

UpdateSummary "Ping was succesful between VM1 and VM2 after iPerf3 finished the run" 
SetTestStateCompleted
exit 0
