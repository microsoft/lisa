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
# Count total number of partitions on system
count=$(grep -c 'sd[a-z][0-9]' /proc/partitions)
LogMsg "Total number of partitions ${count}"
for driveName in /dev/sd*[^0-9]
do
    #
    # Skip /dev/sda and /dev/sdb
    #
    if [[ $driveName == "/dev/sda"  || $driveName == "/dev/sdb" ]] ; then
        continue
    fi
    drives+=($driveName)
    # Delete existing partition
    for (( c=1 ; c<=count; count--))
    do
        (echo d; echo $c ; echo ; echo w) |  fdisk $driveName &>~/summary.log
        sleep 5
    done
    # Partition drive
    (echo n; echo p; echo 1; echo ; echo +500M; echo ; echo w) | fdisk $driveName &>~/summary.log
    sleep 5
    (echo n; echo p; echo 2; echo ; echo; echo ; echo w) | fdisk $driveName &>~/summary.log
    sts=$?
    sleep 5
    if [ 0 -ne ${sts} ]; then
        LogErr "Partitioning disk Failed ${sts}" >> ~/summary.log
        SetTestStateAborted
        exit 1
    else
        LogMsg "Partitioning disk $driveName : Success" >> ~/summary.log
    fi
    # Create filesystem on it
    for fs in "${fileSystems[@]}"
    do
        if [ ${fsSkipped[$fs]} -eq 0 ]
        then
            LogMsg "$fs is NOT skipped" >> ~/fsCheck.log
            fsSkipped[$fs]=1
            echo "y" | mkfs.$fs ${driveName}1  &>~/summary.log; echo "y" | mkfs.$fs ${driveName}2 &>~/summary.log
            sts=$?
            if [ 0 -ne ${sts} ]
            then
                LogErr "Warning: creating filesystem Failed ${sts}" >> ~/summary.log
                LogErr "Warning: test for $fs will be skipped" >> ~/summary.log
            else
                LogMsg "Creating FileSystem $fs on disk  $driveName : Success" >> ~/summary.log
            fi
            break
        else
            LogErr "$fs is skipped" >> ~/fsCheck.log
        fi
    done
    sleep 1
    fs=${fs//,}
    filename="summary-$fs.log"
    cp ~/summary.log ~/$filename
done
SetTestStateCompleted
exit 0
