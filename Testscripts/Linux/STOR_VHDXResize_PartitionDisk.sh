#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

########################################################################
# STOR_VHDXResize_PartitionDisk.sh
# Description:
#    This script will verify if you can create, format, mount, perform
#    read/write operation, unmount and delete a partition on a resized
#    VHDx file.
#
#    The test performs the following steps:
#
#    1. Make sure we have a constants.sh file.
#    2. Creates partition
#    3. Creates filesystem
#    4. Performs read/write operations
#    5. Unmounts partition
#    6. Deletes partition
#
########################################################################

# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" >state.txt
    exit 1
}

# Source constants file and initialize most common variables
UtilsInit

if [ "${fileSystems:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter fileSystems is not defined in constants file."
    SetTestStateAborted
    exit 1
fi

# Verify if guest detects the new drive
if [ ! -e "/dev/sdc" ]; then
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
    testPartition="/dev/sdc2"
    fdiskOption=2
else
    testPartition="/dev/sdc1"
    fdiskOption=1
fi

count=0
for fs in "${fileSystems[@]}"; do
    # Create the new partition
    # delete partition first, mainly used if partition size >2TB, after use parted
    # to rm partition, still can show in fdisk -l even it does not exist in fact.
    (echo d; echo w) | fdisk /dev/sdc 2> /dev/null
    (echo n; echo p; echo $fdiskOption; echo ; echo ;echo w) | fdisk /dev/sdc 2> /dev/null
    if [ $? -gt 0 ]; then
        LogErr "Failed to create partition"
        SetTestStateFailed
        exit 1
    fi
    LogMsg "Partition created"
    sync

    # Format the partition
    LogMsg "Start testing filesystem: $fs"
    command -v mkfs.$fs
    if [ $? -ne 0 ]; then
        LogErr "File-system tools for $fs not present. Skipping filesystem $fs."
        count=`expr $count + 1`
    else
        # Use -f option for xfs filesystem, but ignore parameter for other filesystems
        option=""
        if [ "$fs" = "xfs" ]; then
            option="-f"
        fi
        mkfs -t $fs $option $testPartition
        if [ $? -ne 0 ]; then
            LogErr "Failed to format partition with $fs"
            SetTestStateFailed
            exit 1
        fi
        LogMsg "Successfully formated partition with $fs"
    fi

    if [ $count -eq ${#fileSystems[@]} ]; then
        LogErr "Failed to format partition with ${fileSystems[@]} "
        SetTestStateFailed
        exit 1
    fi

    # Mount partition
    if [ ! -e "/mnt" ]; then
        mkdir /mnt
        if [ $? -ne 0 ]; then
            LogErr "Failed to create mount point"
            SetTestStateFailed
            exit 1
        fi
        LogMsg "Mount point /dev/mnt created"
    fi

    mount $testPartition /mnt
    if [ $? -ne 0 ]; then
        LogErr "Failed to mount partition"
        SetTestStateFailed
        exit 1
    fi
    LogMsg "Partition mount successful"

    # Read/Write mount point
    ./STOR_VHDXResize_ReadWrite.sh

    umount /mnt
    if [ $? -ne 0 ]; then
        LogErr "Failed to unmount partition"
        SetTestStateFailed
        exit 1
    fi
    LogMsg "Unmount partition successful"

    (echo d; echo w) | fdisk /dev/sdc 2> /dev/null
    if [ $? -ne 0 ]; then
        LogErr "Failed to delete partition"
        SetTestStateFailed
        exit 1
    fi
    LogMsg "Succesfully deleted partition"

done

SetTestStateCompleted
