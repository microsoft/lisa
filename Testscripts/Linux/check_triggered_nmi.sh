#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

########################################################################
#
# Description:
#	This script was created to automate the testing of a Linux
#	Integration services. This script will verify if a NMI sent
#	from Hyper-V is received  inside the Linux VM, by checking the
#	/proc/interrupts file.
#	The test performs the following steps:
#	 1. Make sure we have a constants.sh file.
#	 2. Looks for the NMI property of each CPU.
#	 3. For 2012R2, verifies if each CPU has received a NMI.
#	 4. For 2016, verifies only cpu0 has received a NMI.
#
################################################################

set -e

# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

function main() {

    LogMsg "Hyper-V build number: $BuildNumber"

    # Get the NMI cpu
    cpu_count=$(grep CPU -o /proc/interrupts | wc -l)
    LogMsg "${cpu_count} CPUs found"

    #
    # Check host version
    # Prior to WS2016 the NMI is injected to all CPUs of the guest and
    # WS1026 injects it to CPU0 only.
    #

    while read line;
    do
        if [[ $line = *NMI* ]]; then
            for ((  i=0 ;  i<=$cpu_count-1;  i++ ))
            do
                nmiCount=$(echo "$line" | xargs echo | cut -f $(( $i+2 )) -d ' ')
                LogMsg "CPU ${i} interrupt count = ${nmiCount}"

                # CPU0 or 2012R2(14393 > BuildNumber >= 9600) all CPUs should receive NMI
                if [ $i -eq 0 ] || ([ "$BuildNumber" -lt 14393 ] && [ "$BuildNumber" -ge 9600 ]); then
                    if [ "$nmiCount" -ne 0 ]; then
                        LogMsg "NMI received at CPU ${i}"
                    else
                        LogMsg "CPU {$i} did not receive a NMI!"
                        SetTestStateFailed
                        exit 1
                    fi
                # only not CPU0 and 2016 (BuildNumber >= 14393) should not receive NMI
                elif [ "$BuildNumber" -ge 14393 ]; then
                    if [ "$nmiCount" -eq 0 ]; then
                        LogMsg "CPU {$i} did not receive a NMI, this is expected"
                    else
                        LogMsg "CPU {$i} received a NMI!"
                        SetTestStateFailed
                        exit 1
                    fi
                # lower than 9600, return skipped
                else
                    SetTestStateAborted
                fi

            done
        fi
    done < "/proc/interrupts"

    LogMsg "Test completed successfully"
    SetTestStateCompleted
    exit 0
}

main
