#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
########################################################################

#
# Description:
#     This script was created to automate the testing of a Linux
#     Integration services.This script detects the floppy disk
#     and performs read, write and delete operations on it.
#
#     Steps:
#	  1. Make sure that a floppy disk (.vfd) is attached to
#          the Diskette drive.
#	  2. Mount the Floppy Disk.
#     3. Create a file named Sample.txt on the Floppy Disk
#     4. Read the file created
#	  5. Delete the file created
#     6. Unmount the Floppy Disk.
#
################################################################
# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit
#
# Check if floppy module is loaded or not
#
LogMsg "Check if floppy module is loaded"

FLOPPY=`lsmod | grep floppy`
if [[ $FLOPPY != "" ]] ; then
    LogMsg "Floppy disk  module is present"
else
    LogMsg "Floppy disk module is not present in VM . Loading the floppy disk module.."
    modprobe floppy
    sts=$?
    if [ 0 -ne ${sts} ]; then
        LogMsg "Unable to load the floppy disk module!"
        SetTestStateFailed
        exit 0
    else
        LogMsg  "Floppy disk module loaded inside the VM"
        sleep 3
    fi
fi

#
# Format the floppy disk
#
LogMsg "mkfs -t vfat /dev/fd0"
sudo mkfs -t vfat /dev/fd0
sts=$?
if [ $? -ne 0 ]; then
    msg="Unable to mkfs -t vfat /dev/fd0"
    LogMsg "Error: ${msg}"
    SetTestStateAborted
    exit 0
fi

#
# Mount the floppy disk
#
LogMsg "Mounting the floppy disk..."
mkdir -p /mnt/floppy
sudo mount /dev/fd0 /mnt/floppy/
sts=$?
if [ $? -ne 0 ]; then
    LogMsg "Unable to mount the floppy disk"
    LogMsg "Mount floppy disk failed: ${sts}"
    SetTestStateAborted
    exit 0
else
    LogMsg "Floppy disk is mounted successfully inside the VM"
    LogMsg "Floppy disk is detected inside the VM"
fi

cd /mnt/floppy/
LogMsg "Perform write operation on the floppy disk"
LogMsg "Creating a file Sample.txt"
LogMsg "This is a sample file been created for testing..." >Sample.txt
sts=$?
if [ $? -ne 0 ]; then
    LogMsg "Unable to create a file on the Floppy Disk"
    LogMsg "Write to Floppy Disk failed: ${sts}"
   SetTestStateAborted
    exit 0
else
    LogMsg "Sample.txt file created successfully on the floppy disk"
fi

LogMsg "Perform read operation on the floppy disk"
cat Sample.txt
sts=$?
if [ $? -ne 0 ]; then
    LogMsg "Unable to read Sample.txt file from the floppy disk"
    LogMsg "Read file from Floppy disk failed: ${sts}"
    SetTestStateAborted
    exit 0
else
    LogMsg "Sample.txt file is read successfully from the Floppy disk"
fi
LogMsg "Perform delete operation on the Floppy disk"
rm Sample.txt
sts=$?
if [ $? -ne 0 ]; then
    LogMsg "Unable to delete Sample.txt file from the floppy disk"
    LogMsg "Delete file failed: ${sts}"
    SetTestStateFailed
    exit 0
else
   LogMsg "Sample.txt file is deleted successfully from the Floppy disk"
fi

LogMsg "Unmounting the floppy disk..."
cd ~
sudo umount /mnt/floppy/
sts=$?
if [ $? -ne 0 ]; then
    LogMsg "Unable to umount the floppy disk"
    LogMsg "umount failed: ${sts}"
    SetTestStateFailed
    exit 0
else
    LogMsg "Floppy disk unmounted successfully"
    LogMsg "Result: Test Completed Successfully"
    SetTestStateCompleted
fi