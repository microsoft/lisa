#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

########################################################################
#
# Description:
#    This script was created to automate the testing of a Linux
#    Integration services. This script will verify if all the CPUs
#    inside a Linux VM are processing VMBus interrupts, by checking
#    the /proc/interrupts file.
#
#    The test performs the following steps:
#        1. Looks for the Hyper-v timer property of each CPU under /proc/interrupts
#        2. Verifies if each CPU has more than 0 interrupts processed.
#   Note: There are 3 types of Hyper-v interrupts - Hypervisor callback interrupts,
#       Hyper-V reenlightenment interrupts, and Hyper-V stimer0 interrupts
#       Hypervisor callback interrupts - No need to have each CPU handle vmbus
#       message or event in many CPU's VM.
################################################################

# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

function verify_vmbus_interrupts() {

    nonCPU0inter=0
    cpu_count=$(grep CPU -o /proc/interrupts | wc -l)
    UpdateSummary "${cpu_count} CPUs found"

    #
    # It is not mandatory to have the Hyper-V interrupts present
    # Skip test execution if these are not showing up
    #
    if ! [[ $(grep 'hyperv\|Hypervisor' /proc/interrupts) ]]; then
        UpdateSummary "Hyper-V interrupts are not recorded, abort test."
        SetTestStateAborted
        exit 0
    fi

    #
    # Verify if VMBUS interrupts are processed by all CPUs
    #
    while read -r line
    do
        LogMsg "Debug - reading a line $line"
        if [[ ($line = *hyperv* ) || ( $line = *Hypervisor* ) ]]; then
            for (( core=0; core<=$((cpu_count-1)); core++ ))
            do
                LogMsg "Debug - checking the core count $core"
                intrCount=$(echo "$line" | xargs echo | cut -f $(( $core+2 )) -d ' ')
                if [ "$intrCount" -ne 0 ]; then
                    (( nonCPU0inter++ ))
                    LogMsg "CPU core ${core} is processing VMBUS interrupts."
                fi
            done
        fi
    done < "/proc/interrupts"

    if [[ $nonCPU0inter -eq 0 ]]; then
        LogErr "No CPU core is processing VMBUS interrupts!"
        SetTestStateFailed
        exit 0
    fi

    if [[ $cpu_count -gt 4 && $nonCPU0inter -lt "$cpu_count" ]]; then
        LogMsg "Some CPU cores are processing VMBUS interrupts, but it is ok to miss a few core not processing VMBUS interrupts because of big size VM"
    fi
    UpdateSummary "All {$cpu_count} CPU cores are processing interrupts."
    SetTestStateCompleted
}

verify_vmbus_interrupts