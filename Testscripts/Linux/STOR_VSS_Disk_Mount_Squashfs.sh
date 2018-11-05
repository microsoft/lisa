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

install_package squashfs-tools
check_exit_status "squashfs installation" "exit"

testDir="/dir"
testDirSqsh="dir.sqsh"
if [ ! -e ${testDir} ]; then
    mkdir $testDir
fi

mksquashfs ${testDir} ${testDirSqsh}
sts=$?
if [ 0 -ne ${sts} ]; then
    LogMsg "Error: mksquashfs Failed ${sts}"
    SetTestStateFailed
    UpdateSummary " mksquashfs ${testDir} ${testDirSqsh}: Failed"
    exit 1
else
    LogMsg "mksquashfs ${testDir} ${testDirSqsh}"
    UpdateSummary "mksquashfs ${testDir} ${testDirSqsh} : Success"
fi

mount ${testDirSqsh} /mnt -t squashfs -o loop
if [ 0 -ne $? ]; then
    LogMsg "Error: mount squashfs Failed"
    SetTestStateFailed
    UpdateSummary "mount $testDirSqsh Failed"
    exit 1
else
    LogMsg "mount $testDirSqsh"
    UpdateSummary "mount $testDirSqsh : Success"
    SetTestStateCompleted
fi
