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

command -v mkfs.$FILESYS >> ~/summary.log

if [ $? -ne 0 ]; then
    msg="Error: Tools for filesystem $FILESYS are not installed."
    LogErr "$msg"
    UpdateSummary "$msg"
    SetTestStateAborted
    exit 2
fi

os_disk=$(get_OSdisk)
LogMsg "OS disk:$os_disk"

count=0
for disk in $(cat /proc/partitions | grep sd | awk '{print $4}')
do
    if [[ "$disk" != "$os_disk"* ]];
    then
        ((count++))
    fi
done

((count--))

for driveName in /dev/sd*[^0-9];
do
    #
    # Skip the OS disk
    #
    if [ $driveName != "/dev/${os_disk}" ]; then

    # Delete the existing partition
    for (( c=1 ; c<=count; count--))
        do
            (echo d; echo $c ; echo ; echo w) |  fdisk $driveName &>~/summary.log
            sleep 5
        done
    
    # Partition Drive
    (echo n; echo p; echo 1; echo ; echo +500M; echo ; echo w) | fdisk $driveName &>~/summary.log
    sleep 5
    (echo n; echo p; echo 2; echo ; echo; echo ; echo w) | fdisk $driveName &>~/summary.log
    sleep 5
    sts=$?
    if [ 0 -ne ${sts} ]; then
        LogErr "Error:  Partitioning disk Failed ${sts}"
        UpdateSummary "Partitioning disk $driveName : Failed"
        SetTestStateAborted
        exit 1
    else
        UpdateSummary "Partitioning disk $driveName : Success"
    fi

    sleep 1

   # Create file system on it .
   echo "y" | mkfs.$FILESYS ${driveName}1  &>~/summary.log; echo "y" | mkfs.$FILESYS ${driveName}2 &>~/summary.log
   sts=$?
        if [ 0 -ne ${sts} ]; then
            LogErr "Error:  creating filesystem  Failed ${sts}"
            UpdateSummary " Creating FileSystem $filesys on disk $driveName : Failed"
            SetTestStateAborted
            exit 1
        else
            msg="Creating FileSystem $FILESYS on disk  $driveName : Success"
            LogMsg "$msg"
            UpdateSummary "$msg"
        fi

   sleep 1

   # mount the disk
   MountName="/mnt/1"
   if [ ! -e ${MountName} ]; then
     mkdir $MountName
   fi
   MountName1="/mnt/2"
   if [ ! -e ${MountName1} ]; then
     mkdir $MountName1
   fi
   mount ${driveName}1 $MountName &>~/summary.log; mount ${driveName}2 $MountName1 &>~/summary.log
   sts=$?
       if [ 0 -ne ${sts} ]; then
           LogErr "Error:  mounting disk Failed ${sts}"
           UpdateSummary " Mounting disk $driveName on $MountName: Failed"
           SetTestStateAborted
           exit 1
       else
           LogMsg "mounting disk ${driveName}1 on ${MountName}"
           LogMsg "mounting disk ${driveName}2 on ${MountName1}"
           UpdateSummary " Mounting disk ${driveName}1 : Success"
           UpdateSummary " Mounting disk ${driveName}2 : Success"
       fi
fi
done
SetTestStateCompleted
exit 0
