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
items1=(SUBSYSTEM==\"memory\", ACTION==\"add\", ATTR{state}=\"online\")
items2=(SUBSYSTEM!=\"memory\", GOTO=\"memory_hotplug_end\")
#######################################################################
#
# Main script body
#
#######################################################################
# Create the state.txt file so ICA knows we are running

# Cleanup any old summary.log files
if [ -e summary.log ]; then
    rm -rf summary.log
fi

config_path=$(get_bootconfig_path)

# /sys/devices/system/memory/auto_online_blocks = online => when the memory is hot-added, it will be online automatically
if grep CONFIG_MEMORY_HOTPLUG_DEFAULT_ONLINE=y $config_path; then
    LogMsg "CONFIG_MEMORY_HOTPLUG_DEFAULT_ONLINE=y is set in $config_path, then no need to check udev rules on $DISTRO"
    value_of_aob=$(cat /sys/devices/system/memory/auto_online_blocks)
    if [ "$value_of_aob" == "online" ]; then
        LogMsg "Value of /sys/devices/system/memory/auto_online_blocks is expected - online"
        SetTestStateCompleted
        exit 0
    else
        LogErr "Value of /sys/devices/system/memory/auto_online_blocks is unexpected - $value_of_aob"
        SetTestStateFailed
        exit 0
    fi
fi

# Search in /etc/udev and /lib/udev folders
for udevfile in $(find /etc/udev/ /lib/udev/ -name "*.rules*"); do # search for all the .rules files
    match_count=0
    for i in "${items2[@]}"
    do
        grep "$i" "$udevfile" > /dev/null # grep for the udev rule
        sts=$?
        if [ 0 -eq ${sts} ]; then
             match_count=$(expr $match_count + 1)
        fi
    done
    if [ ${#items2[@]} -eq "$match_count" ]; then
        filelist=("${filelist[@]}" $udevfile) # populate an array with the results
    fi
done

for udevfile in $(find /etc/udev/ /lib/udev/ -name "*.rules*"); do # search for all the .rules files
    match_count=0
    for i in "${items1[@]}"
    do
        grep "$i" "$udevfile" > /dev/null # grep for the udev rule
        sts=$?
        if [ 0 -eq ${sts} ]; then
             match_count=$(expr $match_count + 1)
        fi
    done
    if [ ${#items1[@]} -eq "$match_count" ]; then
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
            LogMsg "$rulefile"
        done
    else
        UpdateSummary "Hot-Add udev rule present: Success"
        LogMsg "File is: ${filelist[@]}"
    fi
else
    LogMsg "Error: No Hot-Add udev rules found on the system!"
    SetTestStateFailed
    UpdateSummary "Hot-Add udev rules: Failed!"
    exit 0
fi

SetTestStateCompleted
exit 0
