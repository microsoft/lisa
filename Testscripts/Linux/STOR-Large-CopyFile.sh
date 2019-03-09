#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

. utils.sh || {
    echo "Error: unable to source utils.sh!"
    exit 0
}

UtilsInit

function Test_Local_Copy_File() {
    LogMsg "Start to dd file"

    #dd 5G files
    dd if=/dev/zero of=/root/data bs=2048 count=2500000
    file_size=$(wc -c /root/data | awk '{ print $1}' | tr -d '\r')
    LogMsg "Successful dd file as /root/data"
    LogMsg "Start to copy file to /mnt"

    cp /root/data /mnt
    rm -f /root/data
    file_size1=$(wc -c /mnt/data | awk '{ print $1}' | tr -d '\r')
    LogMsg "file_size after dd=$file_size"

    if [[ $file_size1 = $file_size ]]; then
        LogMsg "Successful copy file"
        LogMsg "Listing directory: ls /mnt/"
        ls /mnt/
        df -h
        rm -rf /mnt/*

        UpdateSummary "Disk test completed for file copy on ${driveName}1 with filesystem ${fs}."
    else
        LogErr "Copying 5G file for ${driveName}1 with filesystem ${fs} failed"
        SetTestStateFailed
        exit 0
    fi
}

# test wget file, wget one 5G file to /mnt which is mounted to disk
function Test_Wget_File() {
    file_basename="$(basename $Wget_Path)"
    wget -O "/mnt/$file_basename" "$Wget_Path"

    file_size="$(curl -sI $Wget_Path | grep Content-Length | awk '{print $2}' | tr -d '\r')"
    file_size1="$(wc -c /mnt/$file_basename | awk '{ print $1}' | tr -d '\r')"
    LogMsg "file_size before wget=$file_size"
    LogMsg "file_size after wget=$file_size1"

    if [[ "$file_size" = "$file_size1" ]]; then
        UpdateSummary "Wget test completed successfully for ${driveName}1 with filesystem ${fs}"
    else
        LogErr "Wget test failed for ${driveName}1 with filesystem ${fs}"
        SetTestStateFailed
        exit 0
    fi
    rm -rf /mnt/*
}

# test copy from nfs path, dd one file to /mnt2 which is mounted to nfs, then copy to /mnt
# which is mounted to disk
function Test_NFS_Copy_File() {
    if [ ! -d "/mnt_2" ]; then
        mkdir /mnt_2
    fi
    mount -t nfs $NFS_Path /mnt_2

    if [ "$?" = "0" ]; then
        LogMsg "Mount nfs successfully from $NFS_Path"
        # dd file
        dd if=/dev/zero of=/mnt_2/data bs="$File_DD_Bs" count="$File_DD_Count"
        sleep 2

        LogMsg "Finish dd file in nfs path, start to copy to drive..."
        cp /mnt_2/data /mnt/
        sleep 2

        file_size=$(wc -c /mnt_2/data | awk '{ print $1}' | tr -d '\r')
        file_size1=$(wc -c /mnt/data | awk '{ print $1}' | tr -d '\r')
        LogMsg "file_size after dd=$file_size"
        LogMsg "file_size after copy=$file_size1"

        rm -rf /mnt/*
        if [ "$file_size" = "$file_size1" ]; then
            UpdateSummary "Drive mount nfs and copy file successfully"
        else
            LogErr "Drive mount nfs and copy file failed"
            SetTestStateFailed
            exit 0
        fi
        umount /mnt_2
    else
        LogErr "Mount nfs from $NFS_Path failed"
        SetTestStateFailed
        exit 0
    fi
}

# Format the disk and create a file system, mount and create file on it.
function Test_File_System_Copy() {
    drive=$1
    fs=$2
    parted -s -- "$drive" mklabel gpt
    parted -s -- "$drive" mkpart primary 64s -64s
    if [ "$?" = "0" ]; then
        sleep 5
        wipefs -a "${driveName}1"
        # IntegrityCheck $driveName
        mkfs."$fs" "${driveName}1"
        if [ "$?" = "0" ]; then
            LogMsg "mkfs.${fs}   ${driveName}1 successful..."
            mount "${driveName}1" /mnt
            if [ "$?" = "0" ]; then
                LogMsg "Drive mounted successfully..."

                # step 1: test for local copy file
                if [[ "$TestLocalCopy" = "True" ]]; then
                     LogMsg "Start to test local copy file"
                     Test_Local_Copy_File
                fi

                if [[ $"TestWget" = "True" ]]; then
                # step 2: wget 5GB file to disk
                     LogMsg "Start to test wget file"
                     Test_Wget_File
                fi

                # step 3: mount nfs file, then copy file to disk
                if [[ "$TestNFSCopy" = "True" ]]; then
                      LogMsg "Start to test copy file from nfs mout point"
                      Test_NFS_Copy_File
                fi

                df -h
                # umount /mnt files
                umount /mnt
                if [ "$?" = "0" ]; then
                      LogMsg "Drive unmounted successfully..."
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
}

# Check for call trace log
./check_traces.sh &

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
    fi

    if [[ $lowStr == scsi* ]];
    then
        diskCount=$((diskCount+1))
    fi
done

echo "constants disk count= $diskCount"

# Compute the number of sd* drives on the system
for driveName in /dev/sd*[^0-9];
do
    # Skip /dev/sda
    if [ ${driveName} = "/dev/sda" ] || [ ${driveName} = "/dev/sdb" ]; then
        continue
    fi

    for fs in "${fileSystems[@]}"; do
        LogMsg "Start testing filesystem: $fs"
        StartTst=$(date +%s.%N)
        command -v mkfs."$fs"
        if [ $? -ne 0 ]; then
            UpdateSummary "File-system tools for $fs not present. Skipping filesystem $fs."
        else
            Test_File_System_Copy "$driveName" "$fs"
            EndTst=$(date +%s.%N)
            DiffTst=$(echo "$EndTst - $StartTst" | bc)
            LogMsg "End testing filesystem: $fs; Test duration: $DiffTst seconds."
        fi
    done
done

SetTestStateCompleted
exit 0
