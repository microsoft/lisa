#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#############################################################################
#
# Check_number_of_channel.sh
# Description:
#   This script will first check the existence of ethtool on vm and that
#   the channel parameters are supported from ethtool.
#   It will check if number of cores is matching with number of current 
#   channel.
#
#############################################################################
# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    SetTestStateAborted
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

# Check if ethtool exist and install it if not
VerifyIsEthtool

if ! GetSynthNetInterfaces; then
    msg="ERROR: No synthetic network interfaces found"
    LogMsg "$msg"
    SetTestStateFailed
    exit 0
fi

# Skip when host older than 2012R2
vmbus_version=$(dmesg | grep "Vmbus version" | awk -F: '{print $(NF)}' | awk -F. '{print $1}')
if [ "$vmbus_version" -lt "3" ]; then
    LogMsg "Info: Host version older than 2012R2. Skipping test."
    SetTestStateAborted
    exit 0
fi

# Check if kernel support channel parameters with ethtool
sts=$(ethtool -l "${SYNTH_NET_INTERFACES[@]}" 2>&1)
if [[ "$sts" = *"Operation not supported"* ]]; then
    LogMsg "$sts"
    LogMsg "Operation not supported. Test Skipped."
    SetTestStateAborted
    exit 0
fi

# Get number of channels
channels=$(ethtool -l "${SYNTH_NET_INTERFACES[@]}" | grep "Combined" | sed -n 2p | grep -o '[0-9]*')
# Get number of cores
cores=$(grep -c processor < /proc/cpuinfo)

if [ "$channels" != "$cores" ]; then
    LogMsg "Expected: $cores channels and actual $channels."
    SetTestStateFailed
    exit 0
fi

msg="Number of channels: $channels and number of cores: $cores."
LogMsg "$msg"
SetTestStateCompleted
exit 0
