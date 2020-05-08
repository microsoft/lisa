#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 2
}
# Source constants file and initialize most common variables
UtilsInit
# Check if Variable in Const file is present or not
if [ ! ${fileSystems} ]; then
    LogErr "No fileSystems variable in constants.sh"
    SetTestStateAborted
    exit 1
fi
# Dictionary to be used in case testing one of the filesystems needs to be skipped
declare -a fsSkipped
# Check if tools for all the filesystems are installed
for fs in "${fileSystems[@]}"
do
    LogMsg "FileSystem check for $fs"
    command -v mkfs.$fs >> ./summary.log
    if [ $? -ne 0 ]; then
        msg="Tools for filesystem $fs are not installed. Test will be skipped."
        LogErr "$msg"
        UpdateSummary "$msg"
        fsSkipped[$fs]=1
    else
        msg="Tools for $fs are installed."
        LogMsg "$msg"
        UpdateSummary "$msg"
        fsSkipped[$fs]=0
    fi
done

delete_partition
make_partition 2

for fs in "${fileSystems[@]}"; do
    if [ ${fsSkipped[$fs]} -eq 0 ]; then
        LogMsg "$fs is NOT skipped"
        make_filesystem 2 "${fs}"
    else
        LogErr "$fs is skipped"
    fi
done
SetTestStateCompleted
exit 0
