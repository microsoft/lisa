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

Integrity_Check() {
    target_device=$1
    test_file="/dev/shm/testsource"
    block_size=$((32 * 1024 * 1024))
    gb=$((1 * 1024 * 1024 * 1024))
    target_size=$(blockdev --getsize64 $target_device)
    let "blocks=$target_size / $block_size"

    if [ "$target_size" -gt "$gb" ]; then
        target_size=$gb
        let "blocks=$target_size / $block_size"
    fi

    blocks=$((blocks - 1))
    mount $target_device /mnt/
    target_device="/mnt/1"
    LogMsg "Creating test data file $test_file with size $block_size"
    LogMsg "We will fill the device $target_device (of size $target_size) with this data (in $blocks) and then will check if the data is not corrupted."
    LogMsg "This will erase all data in $target_device"

    LogMsg "Creating test source file... ($block_size)"

    dd if=/dev/urandom of=$test_file bs=$block_size count=1 status=noxfer 2>/dev/null

    LogMsg "Calculating source checksum..."
    checksum=$(sha1sum $test_file | cut -d " " -f 1)
    LogMsg $checksum
    LogMsg "Checking ${blocks} blocks"
    for ((y = 0; y < $blocks; y++)); do
        LogMsg "Writing block $y to device $target_device ..."
        dd if=$test_file of=$target_device bs=$block_size count=1 seek=$y status=noxfer 2>/dev/null
        LogMsg "Checking block $y ..."
        test_checksum=$(dd if=$target_device bs=$block_size count=1 skip=$y status=noxfer 2>/dev/null | sha1sum | cut -d " " -f 1)
        if [ "$checksum" == "$test_checksum" ]; then
            LogMsg "Checksum matched for block $y"
        else
            LogErr "Checksum mismatch on  block $y for ${target_device} "
            SetTestStateFailed
            exit 0
        fi
    done
    LogMsg "Data integrity test on ${blocks} blocks on drive $1 : success "
    umount /mnt/
    rm -f $test_file
}

SetTestStateRunning
# Count the number of SCSI= and IDE= entries in constants
#
disk_count=0
for entry in $(cat ./constants.sh); do
    # Convert to lower case
    lowStr="$(tr '[A-Z]' '[a-z' <<<"$entry")"

    # does it start wtih ide or scsi
    if [[ $lowStr == ide* ]]; then
        disk_count=$((disk_count + 1))
    fi

    if [[ $lowStr == scsi* ]]; then
        disk_count=$((disk_count + 1))
    fi
done

LogMsg "constants disk count = $disk_count"

#
# Compute the number of sd* drives on the system.
#
sd_count=$(ls /dev/sd*[^0-9] | wc -l)

#
# Subtract the boot disk and resource from the sd_count, then make
# sure the two disk counts match
#
sd_count=$((sd_count - 2))
LogMsg "/dev/sd* disk count = $sd_count"

if [ $sd_count != $disk_count ]; then
    LogErr " disk count ($disk_count) does not match disk count from /dev/sd* ($sd_count)"
    SetTestStateAborted
    exit 0
fi

#
# For each drive, run fdisk -l and extract the drive
# size in bytes.  The setup script will add Fixed
#.vhd of size 1GB, and Dynamic .vhd of 137GB
#
fixed_disk_size=1073741824
disk_4k_size=4096
dynamic_disk_size=136365211648

for drive_name in /dev/sd*[^0-9]; do
    # Skip /dev/sda and /dev/sdb
    if [ ${drive_name} = "/dev/sda" ]; then
        continue
    fi
    if [ ${drive_name} = "/dev/sdb" ]; then
        continue
    fi

    fdisk -l $drive_name >fdisk.dat 2>/dev/null
    # Format the Disk and Create a file system , Mount and create file on it .
    (echo d;echo;echo w)|fdisk $drive_name
    (echo n;echo p;echo 1;echo;echo;echo w)|fdisk $drive_name
    if [ "$?" = "0" ]; then
        sleep 5

        # IntegrityCheck $drive_name
        mkfs.ext4 ${drive_name}1
        if [ "$?" = "0" ]; then
            LogMsg "mkfs.ext4   ${drive_name}1 successful..."
            mount ${drive_name}1 /mnt
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
                    LogMsg "Disk test's completed for ${drive_name}1"
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
        LogErr "Error in executing fdisk  ${drive_name}1"
        SetTestStateFailed
        exit 0
    fi
    # Perform Data integrity test
    Integrity_Check ${drive_name}1
    # The fdisk output appears as one word on each line of the file
    # The 6th element (index 5) is the disk size in bytes
    #
    element_count=0
    for word in $(cat fdisk.dat); do
        element_count=$((element_count + 1))
        if [ $element_count == 5 ]; then
            if [ $word -ne $fixed_disk_size -a $word -ne $dynamic_disk_size -a $word -ne $disk_4k_size ]; then
                LogMsg "Warning: $drive_name has an unknown disk size: $word"
            fi
        fi
    done
done

SetTestStateCompleted

exit 0
