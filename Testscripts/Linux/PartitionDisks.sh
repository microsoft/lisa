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

if [ ! ${FILESYS} ]; then
    LogMsg "No FILESYS variable in constants.sh"
    SetTestStateAborted
    exit 1
fi

install_package "btrfs-progs btrfs-progs-devel xfsprogs xfsprogs-devel"

command -v mkfs.$FILESYS >> ~/summary.log

if [ $? -ne 0 ]; then
    msg="Error: Tools for filesystem $FILESYS are not installed."
    LogErr "$msg"
    UpdateSummary "$msg"
    SetTestStateAborted
    exit 2
fi

delete_partition
make_partition 2
make_filesystem 2 "${FILESYS}"
mount_disk 2
SetTestStateCompleted
exit 0
