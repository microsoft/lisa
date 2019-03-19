#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

net_interface=eth1

# Verify the new NIC received an IP v4 address
LogMsg "Verify the new NIC has an IPv4 address" >> ~/summary.log
ip addr show ${net_interface} | grep "inet\b" > /dev/null
check_exit_status "${net_interface} is up" "exit"
LogMsg "The network interface is ${net_interface}" >> ~/summary.log
initial_address=$(ip a show $net_interface)
LogMsg "Before MAC address change: $initial_address" >> ~/summary.log

# Change MAC
ip link set $net_interface down
LogMsg "Changing MAC address to 02:01:02:03:04:08" >> ~/summary.log
ip link set $net_interface address 02:01:02:03:04:08
if [ $? -ne 0 ]; then
    LogErr "Unable to set static MAC address" >> ~/summary.log
    SetTestStateFailed
    exit 0
fi
ip link set $net_interface up

new_address=$(ip a show $net_interface)
LogMsg "After MAC address change: $new_address" >> ~/summary.log
SetTestStateCompleted
exit 0
