#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

interface="eth1"
ip_local=$1
vm=$2
ip_group=$(ip maddress show $interface | grep inet | head -n1 | awk '{print $2}')
# Source utils.sh
. utils.sh || {
    echo "unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 2
}
# Source constants file and initialize most common variables
UtilsInit

function ConfigureVxlan ()
{
    ip link add vxlan0 type vxlan id 999 local $3 group $4 dev $1
    if [ 0 -ne $? ]; then
        LogMsg "Failed to add vxlan0"
        SetTestStateAborted
        exit 1
    else
        LogMsg "Successfully added vxlan0"
    fi
    ip l set vxlan0 up
    if [ $2 == "local" ]; then
        ip addr add 242.0.0.12/24 dev vxlan0
    else
        ip addr add 242.0.0.11/24 dev vxlan0
    fi
    if [ 0 -ne $? ]; then
        LogErr "Failed to asociate an address for vxlan0"
        SetTestStateAborted
        exit 1
    else
        LogMsg "Successfully added an address for vxlan0."
    fi
}

function CreateTestFolder ()
{
    LogMsg "Creating test directory..."
    mkdir /root/test
    if [ $? -ne 0 ]; then
        LogErr "Failed to create test directory"
        SetTestStateAborted
        exit 1
    fi

    dd if=/dev/zero of=/root/test/data bs=7M count=1024
    if [ $? -ne 0 ]; then
        LogErr "Failed to create test file"
        SetTestStateAborted
        exit 1
    fi

    dd if=/dev/zero of=/root/test/data2 bs=3M count=1024
    if [ $? -ne 0 ]; then
        LogErr "Failed to create test file"
        SetTestStateAborted
        exit 1
    fi
}

stop_firewall
if [ $? -ne 0 ]; then
    LogErr "Failed to stop FIREWALL."
    SetTestStateAborted
    exit 1
fi
service atd start

# configure vxlan
ConfigureVxlan $interface $vm $ip_local $ip_group

if [ $vm == "local" ]; then
    CreateTestFolder
fi

SetTestStateCompleted
exit 0