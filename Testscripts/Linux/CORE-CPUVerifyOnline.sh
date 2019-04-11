#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
#	This script was created to automate the testing of VCPU online or offline.
#   This script will verify if all the CPUs can be offline by checking
#	the /proc/cpuinfo file.
#	The VM is configured with 4 CPU cores as part of the setup script,
#	as each core can't be offline except vcpu0 for a successful test pass.
. utils.sh || {
    echo "unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 1
}

UtilsInit

# Getting the CPUs count
cpu_count=$(grep -i processor -o /proc/cpuinfo | wc -l)
UpdateSummary "${cpu_count} CPU cores detected"

#
# Verifying all CPUs can't be offline except CPU0
#
for ((cpu=1 ; cpu<=$cpu_count ; cpu++)) ;do
    LogMsg "Checking the $cpu on /sys/device/...."
    __file_path="/sys/devices/system/cpu/cpu$cpu/online"
    if [ -e "$__file_path" ]; then
        echo 0 > $__file_path > /dev/null 2>&1
        val=$(cat $__file_path)
        if [ "$val" -ne 0 ]; then
            LogMsg "CPU core ${cpu} can't be offline."
        else
            LogErr "CPU ${cpu} can be offline!"
            SetTestStateFailed
            exit 0
        fi
    fi
done

UpdateSummary "Test pass: no CPU cores could be set to offline mode."
LogMsg "Test completed successfully"
SetTestStateCompleted
exit 0
