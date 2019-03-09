#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

########################################################################
#
# Description:
#   This script compares the host provided Numa Nodes values
#   with the numbers of CPUs and ones detected on a Linux guest VM.
#   To pass test parameters into test cases, the host will create
#   a file named constants.sh. This file contains one or more
#   variable definition.
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

# Get distro
GetDistro

if ! numactl -s; then
    if ! install_package numactl; then
        LogMsg "Error: unable to instal numactl"
        exit 1
    fi
fi

# Check Numa nodes
NumaNodes=$(numactl -H | grep cpu | wc -l)
LogMsg "Info : Detected NUMA nodes = ${NumaNodes}"
LogMsg "Info : Expected NUMA nodes = ${expected_number}"

# We do a matching on the values from host and guest
if ! [[ $NumaNodes = $expected_number ]]; then
    LogErr "Error: Guest VM presented value $NumaNodes and the host has $expected_number . Test Failed!"
    SetTestStateFailed
    exit 0
else
    LogMsg "Info: Numa nodes value is matching with the host. VM presented value is $NumaNodes"
fi

# Check memory size configured in each NUMA node against max memory size
# configured in VM if MemSize test params configured.
if [ -n "$MaxMemSizeEachNode" ]; then
    LogMsg "Info: Max memory size of every node has been set to $MaxMemSizeEachNode MB"
    MemSizeArr=$(numactl -H | grep size | awk '{ print $4 }')
    for i in ${MemSizeArr}; do
        LogMsg "Info: Start checking memory size for node: $i MB"
        if [ "$i" -gt "$MaxMemSizeEachNode" ]; then
            LogErr "Error: The maximum memory size of each NUMA node was $i , which is greater than $MaxMemSizeEachNode MB. Test Failed!"
            SetTestStateFailed
            exit 30
        fi
    done
    LogMsg "The memory size of all nodes are equal or less than $MaxMemSizeEachNode MB."
fi

# If we got here, all validations have been successful and no errors have occurred
LogMsg "NUMA check test Completed Successfully"
SetTestStateCompleted
exit 0
