#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#############################################################################
#
# ETHTOOL-CHECK-CHANNEL.sh
# Description:
#   This script will first check the existence of ethtool on vm and that
#   the channel parameters are supported from ethtool.
#   It will check if number of cores is matching with number of current 
#   channel.
#   At last, this script will change the channel from the ethtool.
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
    LogErr "No synthetic network interfaces found"
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
    LogErr "$sts"
    kernel_version=$(uname -rs)
    LogErr "Getting number of channels from ethtool is not supported on $kernel_version"
    SetTestStateAborted
    exit 0
fi

# Get number of channels
channels=$(ethtool -l "${SYNTH_NET_INTERFACES[@]}" | grep "Combined" | sed -n 2p | grep -o '[0-9]*')
# Get number of cores
cores=$(grep -c processor < /proc/cpuinfo)

if [ "$channels" != "$cores" ]; then
    LogErr "Expected: $cores channels and actual $channels."
    SetTestStateFailed
    exit 0
fi

LogMsg "Number of channels: $channels and number of cores: $cores."

let new_channels=cores-1
if [ $new_channels == 0 ]; then
    LogErr "The number of cores should be greater than 1"
    SetTestStateFailed
    exit 0
fi

# Change the number of channels
sts=$(ethtool -L "${SYNTH_NET_INTERFACES[@]}" combined $new_channels 2>&1)
if [[ "$sts" = *"Operation not supported"* ]]; then
    LogErr "$sts"
    LogErr "Change the number of channels of ${SYNTH_NET_INTERFACES[@]} with $new_channels channels failed"
    SetTestStateFailed
    exit 0
fi

# Get number of channels
channels=$(ethtool -l "${SYNTH_NET_INTERFACES[@]}" | grep "Combined" | sed -n 2p | grep -o '[0-9]*')
if [ "$new_channels" != "$channels" ]; then
    LogErr "Expected: $new_channels channels and actual $channels after change the channels."
    SetTestStateFailed
    exit 0
fi

LogMsg "Change number of channels from $cores to $new_channels successfully"

SetTestStateCompleted
exit 0
