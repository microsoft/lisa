#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" >state.txt
    exit 2
}

# Source constants file and initialize most common variables
UtilsInit

#######################################################################
#
# Main script body
#
#######################################################################
# Create the state.txt file so ICA knows we are running
SetTestStateRunning

# Cleanup any old summary.log files
if [ -e ~/summary.log ]; then
    rm -rf ~/summary.log
fi

# Search in /etc/udev and /lib/udev folders
for udevfile in $(find /etc/udev/ /lib/udev/ -name "*.rules*"); do # search for all the .rules files
    match_count=0
    for i in "${items[@]}"
    do
        grep $i $udevfile > /dev/null # grep for the udev rule
        sts=$?
        if [ 0 -eq ${sts} ]; then
             match_count=`expr $match_count + 1`
        fi
    done
    if [ ${#items[@]} -eq $match_count ]; then
        filelist=("${filelist[@]}" $udevfile) # populate an array with the results
    fi
done

# Now let's check the results
if [ ${#filelist[@]} -gt 0 ]; then # check if we found anything
    if [ ${#filelist[@]} -gt 1 ]; then # check if we found multiple files
        UpdateSummary "Info: More than one udev rules found"
        LogMsg "Following DM udev files were found:"
        # list the files
        for rulefile in "${filelist[@]}"; do
            LogMsg $rulefile
        done
    else
        UpdateSummary "Hot-Add udev rule present: Success"
        LogMsg "File is: ${filelist[@]}"
    fi
else
    LogMsg "Error: No Hot-Add udev rules found on the system!"
    SetTestStateFailed
    UpdateSummary "Hot-Add udev rules: Failed!"
    exit 1
fi

SetTestStateCompleted
exit 0
