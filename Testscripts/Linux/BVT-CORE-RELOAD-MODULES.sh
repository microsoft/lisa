#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

########################################################################
#
# CORE_StressReloadModules.sh
# Description:
#    This script will first check the existence of Hyper-V kernel modules.
#    Then it will reload the modules in a loop in order to stress the system.
#    It also checks that hyperv_fb cannot be unloaded.
#    When done it will bring up the eth0 interface and check again for
#    the presence of Hyper-V modules.
#
################################################################
# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

VerifyModules()
{
    MODULES=~/modules.txt
    lsmod | grep "hv_*" > $MODULES

    # Did VMBus load
    LogMsg "Info: Checking if hv_vmbus is loaded..."
    if ! grep -q "vmbus" $MODULES
    then
        msg="Warning: hv_vmbus not loaded or built-in"
        LogMsg "${msg}"
    fi
    LogMsg "Info: hv_vmbus loaded OK"

    # Did storvsc load
    LogMsg "Info: Checking if storvsc is loaded..."
    if ! grep -q "storvsc" $MODULES
    then
        msg="Warning: hv_storvsc not loaded or built-in"
        LogMsg "${msg}"
    fi
    LogMsg "Info: hv_storvsc loaded OK"

    # Did netvsc load
    LogMsg "Info: Checking if hv_netvsc is loaded..."
    if ! grep -q "hv_netvsc" $MODULES
    then
        msg="Error: hv_netvsc not loaded"
        LogMsg "${msg}"
        SetTestStateFailed
        exit 0
    fi
    LogMsg "Info: hv_netvsc loaded OK"

    #
    # Did utils load
    #
    LogMsg "Info: Checking if hv_utils is loaded..."
    if ! grep -q "utils" $MODULES
    then
        msg="Error: hv_utils not loaded"
        LogMsg "${msg}"
        SetTestStateFailed
        exit 0
    fi
    LogMsg "Info: hv_utils loaded OK"
}

#######################################################################
#
# Main script body
#
#######################################################################
VerifyModules

if modprobe -r hyperv_fb
then
    msg="Error: hyperv_fb could be disabled!"
    LogMsg "${msg}"
    SetTestStateFailed
    exit 0
fi

pass=0
START=$(date +%s)
while [ $pass -lt 100 ]
do
    modprobe -r hv_netvsc
    sleep 1
    modprobe hv_netvsc
    sleep 1
    modprobe -r hv_utils
    sleep 1
    modprobe hv_utils
    sleep 1
    modprobe -r hid_hyperv
    sleep 1
    modprobe hid_hyperv
    sleep 1
    pass=$((pass+1))
    LogMsg $pass
done
END=$(date +%s)
DIFF=$(echo "$END - $START" | bc)

LogMsg "Info: Finished testing, bringing up eth0"
ifdown eth0
ifup eth0
if ! dhclient
then
    msg="Error: dhclient exited with an error"
    LogMsg "${msg}"
    SetTestStateFailed
    exit 0
fi
VerifyModules
ipAddress=$(ifconfig | grep 'inet addr:' | grep -v '127.0.0.1' | cut -d: -f2 | cut -d' ' -f1 | sed -n 1p)
if [[ ${ipAddress} -eq '' ]]; then
    LogMsg "Info: Waiting for interface to receive an IP"
    sleep 30
fi

LogMsg "Info: Test ran for ${DIFF} seconds"

LogMsg "#########################################################"
LogMsg "Result : Test Completed Successfully"
LogMsg "Exiting with state: TestCompleted."
SetTestStateCompleted
exit 0
