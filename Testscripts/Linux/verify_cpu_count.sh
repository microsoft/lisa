#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
#	This script verifies that all the vCPUs are online after bootup.
#

. utils.sh || {
    echo "Unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

UtilsInit

LogMsg "List of CPUs detected: $(ls -d /sys/devices/system/cpu/cpu[0-9]*)"
cpu_count=$(ls -d /sys/devices/system/cpu/cpu[0-9]* | wc -l)
UpdateSummary "${cpu_count} CPU cores detected"

LogMsg "Total CPU count: $cpu_count"
which nproc 1>/dev/null 2>&1 && online_cpu=$(nproc) || online_cpu=$(grep -i ^processor -o /proc/cpuinfo | wc -l)

LogMsg "Online CPU count: $online_cpu"

#
# Verifying all detected CPUs are online
#
if [[ $cpu_count -ne $online_cpu ]];then
        LogErr "All cpu($cpu_count) are not online ($online_cpu)"
        SetTestStateFailed
        exit 0
fi

LogMsg "Test completed successfully"
SetTestStateCompleted
exit 0
