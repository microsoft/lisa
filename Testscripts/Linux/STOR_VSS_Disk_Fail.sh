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

delete_partition
make_partition 2
make_filesystem 2 "${FILESYS}"
mount_disk 2
MountName1="/mnt/2"
fsfreeze -f "$MountName1"
check_exit_status "fsfreeze $MountName1" "exit"
SetTestStateCompleted
exit 0
