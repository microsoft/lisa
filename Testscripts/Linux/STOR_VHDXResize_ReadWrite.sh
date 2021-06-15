#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

########################################################################
# STOR_VHDXResize_ReadWrite.sh
# Description:
#     This script will perform several checks in order to ensure that
#     mounted partition is working properly.
#     The test performs the following steps:
#    1. Creates a file and saves the file size and checksum value
#    2. Creates a folder on the mounted partition
#    3. Copies the created file on that specific path
#    4. Writes, reads and deletes the copied file
#    5. Deletes the previously created folder
#
########################################################################

. utils.sh || {
	echo "ERROR: unable to source utils.sh!"
	echo "TestAborted" > state.txt
	exit 1
}

# Source constants file and initialize most common variables
UtilsInit

mntDir="/mnt"
testDir="$mntDir/testDir"
testFile="$mntDir/testDir/testFile"

# Check for call trace log
CheckCallTracesWithDelay 1

# Read/Write mount point
mkdir $testDir 2> ~/summary.log
check_exit_status "Create file $testDir" "failed"

dd if=/dev/zero of=/root/testFile bs=64 count=1
original_file_size=$(du -b /root/testFile | awk '{ print $1}')
original_checksum=$(sha1sum /root/testFile | awk '{ print $1}')
cp /root/testFile $testDir
rm -f /root/testFile

target_file_size=$(du -b $testFile | awk '{ print $1}')
if [ $original_file_size != $target_file_size ]; then
	LogErr "File sizes do not match: ${original_file_size} - ${target_file_size}"
	SetTestStateFailed
	exit 0
fi

target_checksum=$(sha1sum $testFile | awk '{ print $1}')
if [ $original_checksum != $target_checksum ]; then
	LogErr "File checksums do not match: ${original_checksum} - ${target_checksum}"
	SetTestStateFailed
	exit 0
fi

ls $testFile
check_exit_status "List file $testFile" "failed"

cat $testFile
check_exit_status "Read file $testFile" "failed"

rm $testFile
check_exit_status "Delete file $testFile" "failed"

rmdir $testDir
check_exit_status "Delete directory $testDir" "failed"

LogMsg "Successfully run read/write script"
