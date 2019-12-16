#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#############################################################################
#
# Description:
#    This script will first check the existence of ethtool on vm and will
#    get kinds of information of the driver from ethtool.
#
#############################################################################
# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

#######################################################################
# Main script body
#######################################################################
# Check if ethtool exist and install it if not
if ! VerifyIsEthtool; then
    LogErr "Could not find ethtool in the VM"
    SetTestStateFailed
    exit 0
fi

if ! GetSynthNetInterfaces; then
    LogErr "No synthetic network interfaces found"
    SetTestStateFailed
    exit 0
fi

net_interface=${SYNTH_NET_INTERFACES[0]}
LogMsg "The network interface is $net_interface"

# Get the information of the driver
driver_name=$(ethtool -i $net_interface | grep "driver" | tr ":" " " | awk '{print $2}')
if [ $driver_name ]; then
    LogMsg "Driver name:$driver_name"
else
    LogErr "The driver name is null"
    SetTestStateFailed
    exit 0
fi

driver_version=$(ethtool -i $net_interface | grep "firmware-version" | tr ":" " " | awk '{print $2}')
if [ $driver_version ]; then
    LogMsg "Driver firmware version:$driver_version"
else
    LogErr "The firmware version is null"
    SetTestStateFailed
    exit 0
fi

# Show the device's time stamping capabilities
capabilities=$(ethtool -T $net_interface | grep "Capabilities:" -A 10 | grep "PTP Hardware Clock:" -B 10 | \
               grep -v -e  "Capabilities" -e "PTP Hardware Clock")
LogMsg "Time stamping capabilities:$capabilities"

SetTestStateCompleted
exit 0
