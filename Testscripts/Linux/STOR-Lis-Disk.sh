#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    exit 0
}
#
# Source constants file and initialize most common variables
#
UtilsInit

Integrity-Check() {
    targetDevice=$1
    testFile="/dev/shm/testsource"
    blockSize=$((32 * 1024 * 1024))
    _gb=$((1 * 1024 * 1024 * 1024))
    targetSize=$(blockdev --getsize64 $targetDevice)
    let "blocks=$targetSize / $blockSize"

    if [ "$targetSize" -gt "$_gb" ]; then
        targetSize=$_gb
        let "blocks=$targetSize / $blockSize"
    fi

    blocks=$((blocks - 1))
    mount $targetDevice /mnt/
    targetDevice="/mnt/1"
    LogMsg "Creating test data file $testfile with size $blockSize"
    LogMsg "We will fill the device $targetDevice (of size $targetSize) with this data (in $blocks) and then will check if the data is not corrupted."
    LogMsg "This will erase all data in $targetDevice"

    LogMsg "Creating test source file... ($BLOCKSIZE)"

    dd if=/dev/urandom of=$testFile bs=$blockSize count=1 status=noxfer 2>/dev/null

    LogMsg "Calculating source checksum..."
    checksum=$(sha1sum $testFile | cut -d " " -f 1)
    LogMsg $checksum
    LogMsg "Checking ${blocks} blocks"
    for ((y = 0; y < $blocks; y++)); do
        LogMsg "Writing block $y to device $targetDevice ..."
        dd if=$testFile of=$targetDevice bs=$blockSize count=1 seek=$y status=noxfer 2>/dev/null
        LogMsg "Checking block $y ..."
        testChecksum=$(dd if=$targetDevice bs=$blockSize count=1 skip=$y status=noxfer 2>/dev/null | sha1sum | cut -d " " -f 1)
        if [ "$checksum" == "$testChecksum" ]; then
            LogMsg "Checksum matched for block $y"
        else
            LogErr "Checksum mismatch on  block $y for ${targetDevice} "
            SetTestStateFailed
            exit 0
        fi
    done
    LogMsg "Data integrity test on ${blocks} blocks on drive $1 : success "
    umount /mnt/
    rm -f $testFile
}

SetTestStateRunning
# Count the number of SCSI= and IDE= entries in constants
#
diskCount=1
# Set to 1 because of resource disk
for entry in $(cat ./constants.sh); do
    # Convert to lower case
    lowStr="$(tr '[A-Z]' '[a-z' <<<"$entry")"

    # does it start wtih ide or scsi
    if [[ $lowStr == ide* ]]; then
        diskCount=$((diskCount + 1))
    fi

    if [[ $lowStr == scsi* ]]; then
        diskCount=$((diskCount + 1))
    fi
done

LogMsg "constants disk count = $diskCount"

#
# Compute the number of sd* drives on the system.
#
sdCount=0
for drive in /dev/sd*[^0-9]; do
    sdCount=$((sdCount + 1))
done

#
# Subtract the boot disk from the sdCount, then make
# sure the two disk counts match
#
sdCount=$((sdCount - 1))
LogMsg "/dev/sd* disk count = $sdCount"

if [ $sdCount != $diskCount ]; then
    LogErr " disk count ($diskCount) does not match disk count from /dev/sd* ($sdCount)"
    SetTestStateAborted
    exit 0
fi

#
# For each drive, run fdisk -l and extract the drive
# size in bytes.  The setup script will add Fixed
#.vhd of size 1GB, and Dynamic .vhd of 137GB
#
FixedDiskSize=1073741824
Disk4KSize=4096
DynamicDiskSize=136365211648

for driveName in /dev/sd*[^0-9]; do
    # Skip /dev/sda and /dev/sdb
    if [ ${driveName} = "/dev/sda" ]; then
        continue
    fi
    if [ ${driveName} = "/dev/sdb" ]; then
        continue
    fi

    fdisk -l $driveName >fdisk.dat 2>/dev/null
    # Format the Disk and Create a file system , Mount and create file on it .
    (echo d;echo;echo w)|fdisk $driveName
    (echo n;echo p;echo 1;echo;echo;echo w)|fdisk $driveName
    if [ "$?" = "0" ]; then
        sleep 5

        # IntegrityCheck $driveName
        mkfs.ext4 ${driveName}1
        if [ "$?" = "0" ]; then
            LogMsg "mkfs.ext4   ${driveName}1 successful..."
            mount ${driveName}1 /mnt
            if [ "$?" = "0" ]; then
                LogMsg "Drive mounted successfully..."
                mkdir /mnt/Example
                dd if=/dev/zero of=/mnt/Example/data bs=10M count=50
                if [ "$?" = "0" ]; then
                    LogMsg "Successful created directory /mnt/Example"
                    LogMsg "Listing directory: ls /mnt/Example"
                    ls /mnt/Example
                    rm -f /mnt/Example/data
                    df -h
                    umount /mnt
                    if [ "$?" = "0" ]; then
                        LogMsg "Drive unmounted successfully..."
                    fi
                    LogMsg "Disk test's completed for ${driveName}1"
                else
                    LogErr "Error in creating directory /mnt/Example..."
                    SetTestStateFailed
                    exit 0
                fi
            else
                LogErr "Error in mounting drive..."
                SetTestStateFailed
                exit 0
            fi
        else
            LogErr "Error in creating file system.."
            SetTestStateFailed
            exit 0
        fi
    else
        LogErr "Error in executing fdisk  ${driveName}1"
        SetTestStateFailed
        exit 0
    fi
    # Perform Data integrity test
    Integrity-Check ${driveName}1
    # The fdisk output appears as one word on each line of the file
    # The 6th element (index 5) is the disk size in bytes
    #
    elementCount=0
    for word in $(cat fdisk.dat); do
        elementCount=$((elementCount + 1))
        if [ $elementCount == 5 ]; then
            if [ $word -ne $FixedDiskSize -a $word -ne $DynamicDiskSize -a $word -ne $Disk4KSize ]; then
                LogMsg "Warning: $driveName has an unknown disk size: $word"
            fi
        fi
    done
done

SetTestStateCompleted

exit 0
