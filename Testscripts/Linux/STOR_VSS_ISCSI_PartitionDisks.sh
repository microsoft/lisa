#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################
# Connects to a iscsi target. It takes the target ip as an argument.
#######################################################################
function iScsi_Connect() {
# Start the iscsi service. This is distro-specific.
    GetDistro
    case $DISTRO in
        suse*|sles*)
            /etc/init.d/open-iscsi start
            check_exit_status "iSCSI start" "exit"
        ;;
        ubuntu*)
            service open-iscsi restart
            check_exit_status "iSCSI service restart" "exit"
        ;;
        redhat_*|centos_*)
            service iscsi restart
            check_exit_status "iSCSI service restart" "exit"
        ;;
        *)
            LogMsg "Distro not supported"
            SetTestStateAborted
            UpdateSummary "Distro not supported, test aborted"
            exit 1
    esac

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
# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
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
delete_partition
make_partition 2
make_filesystem 2 "${FILESYS}"
mount_disk 2
SetTestStateCompleted
exit 0