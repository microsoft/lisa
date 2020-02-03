#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

########################################################################
# STOR_VHDXResize_PartitionDisk.sh
# Description:
#    This script will verify if you can create, format, mount, perform
#    read/write operation, unmount and delete a partition on a resized
#    VHDx file. The test performs the following steps:
#    1. Make sure we have a constants.sh file.
#    2. Creates partition
#    3. Creates filesystem
#    4. Performs read/write operations
#    5. Unmounts partition
#    6. Deletes partition
########################################################################

# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 1
}

# Source constants file and initialize most common variables
UtilsInit

if [ "${fileSystems:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter fileSystems is not defined in constants file."
    SetTestStateAborted
    exit 1
fi

if [ "${deviceName:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "Parameter deviceName is not defined in constants file."
    SetTestStateAborted
    exit 1
fi

# Verify if guest detects the new drive
if [ ! -e "$deviceName" ]; then
    LogErr "The Linux guest cannot detect the drive"
    SetTestStateAborted
    exit 1
fi
LogMsg "The Linux guest detected the drive"

# Prepare Read/Write script for execution
chmod +x STOR_VHDXResize_ReadWrite.sh

# If the script is being run a second time modify the following variables
if [ "$rerun" = "yes" ]; then
    LogMsg "Second run of the script"
    testPartition="$deviceName"2
    fdiskOption=2
else
    testPartition="$deviceName"1
    fdiskOption=1
fi

mntDir="/mnt"
count=0
for fs in "${fileSystems[@]}"; do
    # Create the new partition
    # delete partition first, mainly used if partition size >2TB, after use parted
    # to rm partition, still can show in fdisk -l even it does not exist in fact.
    (echo d; echo w) | fdisk "$deviceName" 2> /dev/null
    (echo n; echo p; echo $fdiskOption; echo ; echo ;echo w) | fdisk "$deviceName" 2> /dev/null
    check_exit_status "Create partition" "exit"
    sync

    # Format the partition
    LogMsg "Start testing filesystem: $fs"
    command -v mkfs.$fs
    if [ $? -ne 0 ]; then
        LogErr "File-system tools for $fs not present. Skipping filesystem $fs."
        count=$(expr $count + 1)
    else
        # Use -f/-F option for xfs/ext4 filesystem, but ignore parameter for other filesystems
        option=""
        if [ "$fs" = "xfs" ]; then
            option="-f"
        fi
        if [ "$fs" = "ext4" ]; then
            option="-F"
        fi
        mount | grep $testPartition
        if [ $? -eq 0 ]; then
            umount $mntDir
        fi
        mkfs -t $fs $option $testPartition
        check_exit_status "Format partition with $fs" "exit"
    fi

    if [ $count -eq ${#fileSystems[@]} ]; then
        LogErr "Failed to format partition with ${fileSystems[@]} "
        SetTestStateFailed
        exit 1
    fi

    if [ ! -e $mntDir ]; then
        mkdir $mntDir
        check_exit_status "Create mount point" "exit"
    fi

    mount $testPartition $mntDir
    check_exit_status "Mount partition" "exit"

    # Read/Write mount point
    ./STOR_VHDXResize_ReadWrite.sh

    umount $mntDir
    check_exit_status "Unmount partition" "exit"

    (echo d; echo w) | fdisk "$deviceName" 2> /dev/null
    check_exit_status "Delete partition" "exit"

done

SetTestStateCompleted
