#!/bin/bash
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
############################################################################
# Description:
#   This script verifies that with the Dynamic Memory enabled,
#   load average is lower than 1.
#   This is a regression test based on upstream commit:
#   "Drivers: hv: Ballon: Make pressure posting thread sleep interruptibly"
############################################################################

# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}
# Source constants file and initialize most common variables
UtilsInit
# sleep 8 minutes then check result
LogMsg "Sleeping 8 minutes before checking load average..."
sleep 480
# Check load aveage value of top command
IFS=" " read -r -a load_average <<< "$(top|head -n 1 | awk -F 'load average:' '{print $2}' | awk -F ',' '{print $1,$2,$3}')"
threshold="1"
for value in "${load_average[@]}"; do
    # use awk to compare the value and 1
    LogMsg "value=$value threshold=$threshold"
    st=$(echo "$value $threshold" | awk '{if ($1 < $2) print 0; else print 1}')
    if [ $st -eq "1" ]; then
        LogErr "The load average value of top is too high: $value"
        SetTestStateFailed
        exit 0
    fi
done
LogMsg "Test successful. Top load average value is lower than 1"
SetTestStateCompleted
exit 0