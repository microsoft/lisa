#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

########################################################################
# STOR_VHDXResize_PartitionDiskOver2TB.sh
# Description:
#    This script will verify if you can create, format, mount, perform
#    read/write operation, unmount and delete a partition on a VHDx
#	 file larger than 2TB. The test performs the following steps:
#    1. Make sure we have a constants.sh file.
#    2. Creates partition
#    3. Creates filesystem
#    4. Performs read/write operations
#    5. Unmounts partition
#    6. Deletes partition
########################################################################

. ./utils.sh || {
	echo "ERROR: unable to source utils.sh!"
	echo "TestAborted" > state.txt
	exit 1
}

# Source constants file and initialize most common variables
UtilsInit

SetTestStateRunning

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

# Support $NewSize and $growSize,if not define $NewSize, check $growSize
if [ -z $NewSize ] && [ -n $growSize ]; then
  NewSize=$growSize
  LogMsg "Target parted size is $NewSize"
fi
install_package "parted"
# Create the new partition
parted "$deviceName" -s mklabel gpt mkpart primary 0GB $NewSize
if [ $? -gt 0 ]; then
    LogErr "Failed to create partition by parted with $NewSize"
    SetTestStateFailed
    exit 1
fi
LogMsg "Partition created by parted"
sync

# Format the partition
count=0
for fs in "${fileSystems[@]}"; do
    LogMsg "Start testing filesystem: $fs"
    command -v mkfs.$fs
    if [ $? -ne 0 ]; then
        LogMsg "File-system tools for $fs not present. Skipping filesystem $fs."
        count=$(expr $count + 1)
    else
        mkfs -t $fs "$deviceName"1
        check_exit_status "Format partition with $fs" "exit"
        break
    fi
done

if [ $count -eq ${#fileSystems[@]} ]; then
    LogErr "Failed to format partitions for all given file systems"
    SetTestStateFailed
    exit 1
fi

# Mount partition
if [ ! -e "/mnt" ]; then
    mkdir /mnt
    check_exit_status "Create mount point" "exit"
fi

mount "$deviceName"1 /mnt
check_exit_status "Partition mount" "exit"

# Read/Write mount point
chmod +x STOR_VHDXResize_ReadWrite.sh
./STOR_VHDXResize_ReadWrite.sh

umount /mnt
check_exit_status "Unmount partition" "exit"

parted "$deviceName" -s rm 1
check_exit_status "Delete partition" "exit"

SetTestStateCompleted
