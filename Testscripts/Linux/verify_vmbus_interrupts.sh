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
#           a) Hypervisor callback interrupts: vmbus messages/events. It could have CPU
#              with 0 interrupts in big VM size.
#           b) Hyper-V reenlightenment interrupts: Only used in Nexted virtualization.
#           c) Hyper-V stimer0 interrupts: new Hyper-V timer, and if exsts, this count
#              should not be zero.
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
    cat /proc/interrupts > interrupts
    while read line
    do
        if [[ ($line = *Hyper-V* ) || ( $line = *Hypervisor* ) ]]; then
            for (( core=0; core<=$cpu_count-1; core++ ))
            do
                intrCount=$(echo "$line" | xargs echo |cut -f $(( $core+2 )) -d ' ')
                if [ "$intrCount" -ne 0 ]; then
                    (( nonCPU0inter++ ))
                    UpdateSummary "CPU core ${core} is processing VMBUS interrupts."
                fi
            done
        fi
    done < interrupts

    if [ $nonCPU0inter -eq 0 ]; then
        LogMsg "Total CPU counts: $cpu_count"
        LogMsg "The number of CPU counts using interrupts: $nonCPU0inter"
        LogErr "None of CPU cores are processing VMBUS interrupts!"
        SetTestStateFailed
    else
        UpdateSummary "All {$cpu_count} CPU cores are processing interrupts."
        SetTestStateCompleted
    fi
}

verify_vmbus_interrupts
exit 0