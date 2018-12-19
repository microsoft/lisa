#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
#   Verify with lspci if the necessary module is loaded. Also verify
# if VF is present in /sys/devices
#
######################################################################
echo "NIC_COUNT=1" >> sriov_constants.sh

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

UpdateSummary "VF is in use"
SetTestStateCompleted
exit 0