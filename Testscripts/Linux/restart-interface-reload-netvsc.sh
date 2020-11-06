#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 2
}

# Source constants file and initialize most common variables
UtilsInit
ExitCode=0

Run()
{
    rm -rf CurrentOutput.txt
    rm -rf CurrentError.txt
    LogMsg "Running $1"
    $1 > CurrentOutput.txt 2> CurrentError.txt
    ReturnCode=$?
    CurrentOutput="$(<CurrentOutput.txt)"
    CurrentError="$(<CurrentError.txt)"
    LogMsg "STDOUT: $CurrentOutput"
    LogMsg "STDERR: $CurrentError"
    if [[ "$ReturnCode" == "0" ]];
    then
        true
    else
        false
    fi
}

############################################################
# Main body
############################################################
config_path=$(get_bootconfig_path)
netvsc_includes=$(grep CONFIG_HYPERV_NET=y "$config_path")
if [ $netvsc_includes ]; then
    LogMsg "Module hv_netvsc is builtin, skip the case."
    SetTestStateSkipped
    exit 0
fi

if [[ "$TestIterations" == "" ]] || [[ -z $TestIterations ]];
then
    LogMsg "Setting Test Iterations to $TestIterations"
    TestIterations=1
else
    LogMsg "Setting Test Iterations to $TestIterations from constants.sh"
fi

LogMsg "*********INFO: Starting test execution ... *********"
NetworkInterface="eth0"

TestCount=0
while [[ $TestCount -lt $TestIterations ]];
do
    TestCount=$(( TestCount + 1 ))
    LogMsg "Test Iteration : $TestCount"
    Run "ip link set $NetworkInterface down"
    if [[ "$?" == "0" ]];
    then
        LogMsg "Bringing down interface $NetworkInterface : SUCCESS"
        Run 'rmmod hv_netvsc'
        if [[ "$?" == "0" ]];
        then
            LogMsg "rmmod hv_netvsc : SUCCESS"
            Run 'modprobe hv_netvsc'
            if [[ "$?" == "0" ]];
            then
                LogMsg "modprobe hv_netvsc : SUCCESS"
                Run "ip link set $NetworkInterface up"
                if [[ "$?" == "0" ]];
                then
                        LogMsg "Bringing up interface $NetworkInterface : SUCCESS"
                        Run "dhclient -r"
                        Run "dhclient"
                else
                        LogMsg "Bringing up interface $NetworkInterface : Failed."
                        ExitCode=$(( ExitCode + 1 ))
                fi
            else
                LogMsg "modprobe hv_netvsc : Failed."
                ExitCode=$(( ExitCode + 1 ))
            fi
        else
            LogMsg "rmmod hv_netvsc : Failed."
            ExitCode=$(( ExitCode + 1 ))
        fi
    else
        LogMsg "Bringing down interface $NetworkInterface : Failed."
        ExitCode=$(( ExitCode + 1 ))
    fi
    LogMsg "Sleeping 5 seconds"
    sleep 5
done

# Conclude the result
if [[ "$ExitCode" == "0" ]];
then
    SetTestStateCompleted
else
    SetTestStateFailed
fi

LogMsg "*********INFO: Script execution completed. *********"
exit 0