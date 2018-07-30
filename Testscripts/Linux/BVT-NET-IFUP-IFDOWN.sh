#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

NetInterface="eth0"
TestCount=0
REMOTE_SERVER="8.8.4.4"
LoopCount=10

PingCheck()
{
    if ! ping "$REMOTE_SERVER" -c 4; then
        # On azure ping is disabled so we need another test method
        if ! wget google.com; then
            msg="Error: ${NetInterface} ping and wget failed on try ${1}."
            LogMsg "$msg"
            SetTestStateFailed
            exit 0
        fi
    else
        msg="Ping ${NetInterface}: Passed on try ${1}"
        LogMsg "$msg"
    fi
}

ChangeInterfaceState()
{
    if ! ip link set dev "$NetInterface" "$1"; then
        msg="Error: Bringing interface ${1} ${NetInterface} failed"
        LogMsg "$msg"
        SetTestStateFailed
        exit 0
    else
        msg="Interface ${NetInterface} was put ${1}"
        LogMsg "$msg"
    fi
    sleep 5 
}

ReloadNetvsc()
{
    if ! modprobe $1 hv_netvsc; then
        msg="modprobe ${1} hv_netvsc : Failed"
        LogMsg "$msg"
        SetTestStateFailed
        exit 0
    else
        sleep 1
        msg="modprobe ${1} hv_netvsc : Passed"
        LogMsg "$msg"
    fi    
}

### Main script ###
# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}
# Source constants file and initialize most common variables
UtilsInit

while [ "$TestCount" -lt "$LoopCount" ]
do
    TestCount=$((TestCount+1))
    LogMsg "Test Iteration : $TestCount"

    # Unload hv_netvsc
    ReloadNetvsc "-r"

    # Load hv_netvsc
    ReloadNetvsc
done

# Clean all dhclient processes, get IP & try ping
LoopCount=4
TestCount=1
ChangeInterfaceState "up"
kill "$(pidof dhclient)"
dhclient -r && dhclient
sleep 15
PingCheck $TestCount

while [ "$TestCount" -lt "$LoopCount" ]
do
    TestCount=$((TestCount+1))
    LogMsg "Test Iteration : ${TestCount}"
    ChangeInterfaceState "down"
    ChangeInterfaceState "up"
    kill "$(pidof dhclient)"
    dhclient -r && dhclient
    sleep 15
    PingCheck "$TestCount"
done

LogMsg "#########################################################"
LogMsg "Result : Test Completed Successfully"
SetTestStateCompleted
exit 0
