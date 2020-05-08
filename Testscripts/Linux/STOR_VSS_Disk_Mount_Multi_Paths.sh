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
if [ ! ${FILESYS} ]; then
    LogErr "No FILESYS variable in constants.sh"
    SetTestStateAborted
    exit 1
fi
command -v mkfs.$FILESYS >> ~/summary.log
if [ $? -ne 0 ]; then
    msg="Tools for filesystem $FILESYS are not installed."
    LogErr "$msg"
    UpdateSummary "$msg"
    SetTestStateAborted
    exit 2
fi

delete_partition
make_partition 2
make_filesystem 2 "${FILESYS}"
sleep 1
# mount the same partition to two paths
MountName="/mnt/1"
if [ ! -e ${MountName} ]; then
    mkdir $MountName
fi
MountName1="/mnt/2"
if [ ! -e ${MountName1} ]; then
    mkdir $MountName1
fi
mount ${driveName}1 $MountName
check_exit_status "Mounting disk ${driveName}1 on $MountName" "exit"
mount ${driveName}1 $MountName1
check_exit_status "Mounting disk ${driveName}1 on $MountName1" "exit"
SetTestStateCompleted
exit 0