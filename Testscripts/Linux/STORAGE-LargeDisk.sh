#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Check_For_Error() {
    distro=$(grep -ihs "Ubuntu\|SUSE\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux" /etc/{issue,*release,*version})
    if [[ $distro = *"ubuntu"* || $distro = *"debian"* ]]; then
        messages="/var/log/syslog"
    else
        messages="/var/log/messages"
    fi
    while true; do
        if [[ $(tail $messages | grep -i "No additional sense information") ]]; then
            LogErr "System hanging at mkfs $1"
            SetTestStateAborted
            exit 0
        fi
        sleep 3
    done
 }

function Integrity_Check() {
    targetDevice=$1
    testFile="/dev/shm/testsource"
    blockSize=$((32*1024*1024))
    _gb=$((1*1024*1024*1024))
    targetSize="$(blockdev --getsize64 "$targetDevice")"
    let "blocks=$targetSize / $blockSize"

    if [ "$targetSize" -gt "$_gb" ] ; then
        targetSize="$_gb"
        let "blocks=$targetSize / $blockSize"
    fi

    blocks=$((blocks-1))
    mount "$targetDevice" /mnt/
    targetDevice="/mnt/1"

    LogMsg "Creating test data file $testfile with size $blockSize"
    LogMsg "Creating test source file... ($blockSize)"

    dd if=/dev/urandom of="$testFile" bs="$blockSize" count=1 status=noxfer 2> /dev/null

    LogMsg "Calculating source checksum..."

    checksum=$(sha1sum $testFile | cut -d " " -f 1)
    echo "$checksum"

    LogMsg "Checking ${blocks} blocks"
    for ((y=0 ; y<blocks ; y++)) ; do
        LogMsg "Writing block $y to device $targetDevice ..."
        dd if=$testFile of=$targetDevice bs=$blockSize count=1 seek=$y status=noxfer 2> /dev/null

        LogMsg "Checking block $y ..."
        testChecksum=$(dd if=$targetDevice bs=$blockSize count=1 skip=$y status=noxfer 2> /dev/null | sha1sum | cut -d " " -f 1)
        if [ "$checksum" == "$testChecksum" ] ; then
            LogMsg "Checksum matched for block $y"
        else
            LogErr "Checksum mismatch on  block $y for ${targetDevice} "
            SetTestStateFailed
            exit 0
        fi
    done

    UpdateSummary "Data integrity test on ${blocks} blocks on drive $1 : success"
    umount /mnt/
    rm -f $testFile
}

# Format the disk and create a file system, mount and create file on it.
function Test_File_System() {
    drive=$1
    fs=$2
    parted -s -- "$drive" mklabel gpt
    parted -s -- "$drive" mkpart primary 64s -64s

    if [ "$?" = "0" ]; then
        sleep 5
        wipefs -a "${driveName}1"
        Check_For_Error "${driveName}1" &

        # Integrity_Check $driveName
        mkfs."$fs" "${driveName}1"
        if [ "$?" = "0" ]; then
            LogMsg "mkfs.${fs}   ${driveName}1 successful..."
            mount "${driveName}1" /mnt
            if [ "$?" = "0" ]; then
                LogMsg "Drive mounted successfully..."
                mkdir /mnt/Example
                dd if=/dev/zero of=/mnt/Example/data bs=10M count=50
                if [ "$?" = "0" ]; then
                    LogMsg "Successful created directory /mnt/Example"
                    LogMsg "Listing directory: ls /mnt/Example"
                    ls /mnt/Example
                    df -h
                    rm -rf /mnt/*
                    umount /mnt
                    if [ "$?" = "0" ]; then
                        LogMsg "Drive unmounted successfully..."
                    fi
                    UpdateSummary "Disk test completed for ${driveName}1 with filesystem ${fs}"
                else
                    LogErr "Error in creating directory /mnt/Example... for ${fs}"
                fi
            else
                LogErr "Error in mounting drive..."
                SetTestStateFailed
            fi
        else
            LogErr "Error in creating file system ${fs}.."
            SetTestStateFailed
        fi
    else
        LogErr "Error in executing parted  ${driveName}1 for ${fs}"
        SetTestStateFailed
    fi

    # Perform Data integrity test
    Integrity_Check "${driveName}1"
}

. utils.sh || {
    echo "Error: unable to source utils.sh!"
    exit 0
}

UtilsInit

# Count the number of SCSI= and IDE= entries in constants
diskCount=0
for entry in $(cat ./constants.sh)
do
    # Convert to lower case
    lowStr="$(tr '[A-Z]' '[a-z' <<<"$entry")"

    # does it start wtih ide or scsi
    if [[ $lowStr == ide* ]];
    then
        diskCount=$((diskCount+1))
        # Generation 2 VM does not support IDE disk
        if [ -d /sys/firmware/efi ]; then
            UpdateSummary "Generation 2 VM does not support IDE disk, skip test"
            SetTestStateSkipped
            exit 0
        fi
    fi

    if [[ $lowStr == scsi* ]];
    then
        diskCount=$((diskCount+1))
    fi
done

echo "constants disk count = $diskCount"


# Compute the number of sd* drives on the system.
sdCount=0
for drive in /dev/sd*[^0-9]
do
    sdCount=$((sdCount+1))
done

# Subtract the boot disk from the sdCount, then make
# sure the two disk counts match
sdCount=$((sdCount-2))
echo "/dev/sd* disk count = $sdCount"

if [ $sdCount != $diskCount ];
then
    LogErr "constants.sh disk count ($diskCount) does not match disk count from /dev/sd* ($sdCount)"
    SetTestStateAborted
    exit 0
fi

for driveName in /dev/sd*[^0-9];
do

    # Skip /dev/sda
    if [ "${driveName}" = "/dev/sda" ] || [ "${driveName}" = "/dev/sdb" ]; then
        continue
    fi

    for fs in "${fileSystems[@]}"; do
        LogMsg "Start testing filesystem: $fs"
        StartTst=$(date +%s.%N)
        command -v mkfs."$fs"
        if [ $? -ne 0 ]; then
            UpdateSummary "File-system tools for $fs not present. Skipping filesystem $fs."
        else
            Test_File_System "$driveName" "$fs"
            EndTst=$(date +%s.%N)
            DiffTst=$(echo "$EndTst - $StartTst" | bc)
            LogMsg "End testing filesystem: $fs; Test duration: $DiffTst seconds."
        fi
    done
done

SetTestStateCompleted

exit 0
