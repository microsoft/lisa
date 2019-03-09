#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
count=0
#######################################################################
# Connects to a iscsi target. It takes the target ip as an argument.
#######################################################################
function iScsi_Connect() {
# Start the iscsi service. This is distro-specific.
    if is_suse ; then
        /etc/init.d/open-iscsi start
        check_exit_status "iSCSI start" "exit"
    elif is_ubuntu ; then
        service open-iscsi restart
        check_exit_status "iSCSI service restart" "exit"
    elif is_fedora ; then
        service iscsi restart
        check_exit_status "iSCSI service restart" "exit"
    else
        LogMsg "Distro not supported"
        SetTestStateAborted
        UpdateSummary "Distro not supported, test aborted"
        exit 1
    fi

    # Discover the IQN
    iscsiadm -m discovery -t st -p ${TargetIP}
    if [ 0 -ne $? ]; then
        LogErr "iSCSI discovery failed. Please check the target IP address (${TargetIP})"
        SetTestStateAborted
        UpdateSummary " iSCSI service: Failed"
        exit 1
    elif [ ! ${IQN} ]; then  # Check if IQN Variable is present in constants.sh, else select the first target.
        # We take the first IQN target
        IQN=$(iscsiadm -m discovery -t st -p ${TargetIP} | head -n 1 | cut -d ' ' -f 2)
    fi

    # Now we have all data necesary to connect to the iscsi target
    iscsiadm -m node -T ${IQN} -p  ${TargetIP} -l
    check_exit_status "iSCSI connection to ${TargetIP} >> ${IQN}"
}


#######################################################################
#
# Main script body
#
#######################################################################

# Cleanup any old summary.log files
if [ -e ~/summary.log ]; then
    rm -rf ~/summary.log
fi

# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" >state.txt
    exit 2
}

# Source constants file and initialize most common variables
UtilsInit

# Source the constants file
if [ -e $HOME/constants.sh ]; then
    . $HOME/constants.sh
else
    LogErr "Unable to source the constants file."
    exit 1
fi

# Check if Variable in Const file is present or not
if [ ! ${FILESYS} ]; then
    LogErr "No FILESYS variable in constants.sh"
    SetTestStateAborted
    exit 1
else
    LogMsg "File System: ${FILESYS}"
fi

if [ ! ${TargetIP} ]; then
    LogErr "No TargetIP variable in constants.sh"
    SetTestStateAborted
    exit 1
else
    LogMsg "Target IP: ${TargetIP}"
fi

if [ ! ${IQN} ]; then
    LogErr "No IQN variable in constants.sh. Will try to autodiscover it"
else
    LogMsg "IQN: ${IQN}"
fi

# Connect to the iSCSI Target
iScsi_Connect
check_exit_status "iScsi connection to $TargetIP" "exit"

# Count the Number of partition present in added new Disk .
for disk in $(cat /proc/partitions | grep sd | awk '{print $4}')
do
        if [[ "$disk" != "sda"*  && "$disk" != "sdb"* ]];
        then
                ((count++))
        fi
done

((count--))

# Format, Partition and mount all the new disk on this system.
for driveName in /dev/sd*[^0-9];
do
    #
    # Skip /dev/sda and /dev/sdb
    #
    if [[ $driveName == "/dev/sda"  || $driveName == "/dev/sdb" ]] ; then
        continue
    fi

    # Delete the exisiting partition
    for (( c=1 ; c<=count; count--))
        do
            (echo d; echo $c ; echo ; echo w) | fdisk $driveName
        done

    # Partition Drive
    (echo n; echo p; echo 1; echo ; echo +500M; echo ; echo w) | fdisk $driveName
    (echo n; echo p; echo 2; echo ; echo; echo ; echo w) | fdisk $driveName
    sts=$?
    if [ 0 -ne ${sts} ]; then
        echo "ERROR:  Partitioning disk Failed ${sts}"
        SetTestStateAborted
        UpdateSummary " Partitioning disk $driveName : Failed"
        exit 1
    else
        LogMsg "Partitioning disk $driveName : Success"
        UpdateSummary " Partitioning disk $driveName : Success"
    fi

    sleep 1

# Create file sytem on it .
    echo "y" | mkfs.$FILESYS ${driveName}1  ; echo "y" | mkfs.$FILESYS ${driveName}2
    check_exit_status "Creating·FileSystem·$filesys·on·disk·$driveName" "exit"

   sleep 1

# mount the disk .
   MountName="/mnt/1"
   if [ ! -e ${MountName} ]; then
       mkdir $MountName
   fi
   MountName1="/mnt/2"
   if [ ! -e ${MountName1} ]; then
       mkdir $MountName1
   fi
   mount  ${driveName}1 $MountName ; mount  ${driveName}2 $MountName1
   sts=$?
       if [ 0 -ne ${sts} ]; then
           LogErr "mounting disk Failed ${sts}"
           SetTestStateAborted
           UpdateSummary " Mounting disk $driveName on $MountName: Failed"
           exit 1
       else
           LogMsg "mounting disk ${driveName}1 on ${MountName}"
           LogMsg "mounting disk ${driveName}2 on ${MountName1}"
           UpdateSummary " Mounting disk ${driveName}1 : Success"
           UpdateSummary " Mounting disk ${driveName}2 : Success"
       fi
done

SetTestStateCompleted
exit 0
