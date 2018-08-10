#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#####################################################################
# Description:
#   This script verifies that the status of some values of with ethtool.
#
#   Steps:
#   1. Verify configuration file constants.sh
#   2. Determine interface(s) to check
#   3. Check TSO,  scatter-gather rx-checksumming and tx-checksumming
#
#   The test is successful if all interfaces are on.
#
#   No parameters required.
#
#   Optional parameters:
#       TC_COVERED
#
#   Parameter explanation:
#   TC_COVERED is the LIS testcase number
#
#############################################################################################################
declare __synth_iface
declare -a ETHTOOL_KEYS
ETHTOOL_KEYS=("tcp-segmentation-offload" "scatter-gather" "rx-checksumming" "tx-checksumming")

# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

# Check if ethtool exist and install it if not
VerifyIsEthtool

GetSynthNetInterfaces
if ! GetSynthNetInterfaces; then
    msg="ERROR: No synthetic network interfaces found"
    LogMsg "$msg"
    SetTestStateFailed
    exit 0
fi

for __synth_iface in "${SYNTH_NET_INTERFACES[@]}"; do
    if ! ethtool -k "$__synth_iface"; then
        msg="Can't get the related value of synthetic network adapter with ethtool"
        LogMsg "${msg}"
        SetTestStateFailed
        exit 0
    fi

    for __key in "${ETHTOOL_KEYS[@]}"; do
        value=$(ethtool -k "$__synth_iface" | grep "$__key" |awk -F " " '{print $2}')
        value=${value:0:2}
        if [ "$value" != "on" ]; then
            msg="ERROR: The ${__key} is not set as on"
            LogMsg "$msg"
            SetTestStateFailed
            exit 0
        fi
    done
    msg="All values are set right"
    LogMsg "${msg}"
done

LogMsg "Updating test case state to completed"
SetTestStateCompleted
exit 0
