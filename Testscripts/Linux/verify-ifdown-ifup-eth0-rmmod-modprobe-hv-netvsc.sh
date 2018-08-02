#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
#
# Sample script to run sysbench.
# In this script, we want to bench-mark device IO performance on a mounted folder.
# You can adapt this script to other situations easily like for stripe disks as RAID0.
# The only thing to keep in mind is that each different configuration you're testing
# must log its output to a different directory.
#
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
#       Main body
############################################################
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
    Run "ifdown $NetworkInterface"
    if [[ "$?" == "0" ]];
    then
        LogMsg "ifdown $NetworkInterface : SUCCESS"
        Run 'rmmod hv_netvsc'
        if [[ "$?" == "0" ]];
        then
            LogMsg "rmmod hv_netvsc : SUCCESS"
            Run 'modprobe hv_netvsc'
            if [[ "$?" == "0" ]];
            then
                LogMsg "modprobe hv_netvsc : SUCCESS"
                Run "ifup $NetworkInterface"
                if [[ "$?" == "0" ]];
                then
                        LogMsg "ifup $NetworkInterface : SUCCESS"
                else
                        LogMsg "ifup $NetworkInterface : Failed."
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
        LogMsg "ifdown $NetworkInterface : Failed."
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
