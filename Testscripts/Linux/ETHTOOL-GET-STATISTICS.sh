#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#############################################################################
ChangeMTU() {
    test_iface=$1
    value=$2
    LogMsg "Setting MTU $value on $test_iface" >> ~/summary.log
    sudo ip link set dev $test_iface mtu $value
    check_exit_status "MTU set to $value on $test_iface" "exit"
}

# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

# Check if ethtool exist and install it if not
if ! VerifyIsEthtool; then
    LogErr "Could not find ethtool in the VM"
    SetTestStateFailed
    exit 0
fi

net_interface=eth0
# Changing MTU
ChangeMTU $net_interface 1505
ChangeMTU $net_interface 2048
ChangeMTU $net_interface 4096

# Get NIC statistics using ethtool
LogMsg "Getting NIC statistics with ethtool"
stats=$(ethtool -S $net_interface)
if [ $? -ne 0 ]; then
    LogErr "Failed to get NIC statistics with ethtool !" >> ~/summary.log
    SetTestStateFailed
    exit 0
else
    LogMsg "$stats"
fi
LogMsg "Getting NIC statistics per CPU with ethtool"
statspcup=$(ethtool -S $net_interface | grep 'queue_')
if [ $? -ne 0 ]; then
    LogErr "Failed to get NIC statistics per CPU with ethtool !" >> ~/summary.log
    SetTestStateFailed
    exit 0
else
    LogMsg "$statspcup"
fi

SetTestStateCompleted
exit 0