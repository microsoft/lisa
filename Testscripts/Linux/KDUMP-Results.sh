#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#
# Source utils.sh to get more utils
# Get $DISTRO, LogMsg directly from utils.sh
#
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    exit 0
}

#
# Source constants file and initialize most common variables
#
UtilsInit
vm2ipv4=$1

Check_VMcore()
{
    if ! [[ $(find /var/crash/*/vmcore -type f -size +10M) ]]; then
        LogErr "Test Failed. No file was found in /var/crash of size greater than 10M."
        SetTestStateFailed
        exit 0
    else
        UpdateSummary "Test Successful. Proper file was found."
        SetTestStateCompleted
    fi
}

Verify_RemoteStatus()
{
    array_status=( $status )
    exit_code=${array_status[-1]}
    if [ "$exit_code" -eq 0 ]; then
        UpdateSummary "Test Successful. Proper file was found on nfs server."
        SetTestStateCompleted
    else
        LogErr "Test Failed. No file was found on nfs server of size greater than 10M."
        SetTestStateFailed
        exit 0
    fi
}

#######################################################################
#
# Main script body
#
#######################################################################
GetDistro
case $DISTRO in
    centos* | redhat* | fedora*)
        if [[ $vm2ipv4 != "" ]]; then
            status=$(ssh -i /root/.ssh/"${SSH_PRIVATE_KEY}" -o StrictHostKeyChecking=no root@"${vm2ipv4}" "find /mnt/var/crash/*/vmcore -type f -size +10M; echo $?")
            Verify_RemoteStatus
        else
            Check_VMcore
        fi
    ;;
    ubuntu*|debian*)
        if [[ $vm2ipv4 != "" ]]; then
            status=$(ssh -i /root/.ssh/"${SSH_PRIVATE_KEY}" -o StrictHostKeyChecking=no root@"${vm2ipv4}" "find /mnt/* -type f -size +10M; echo $?")
            Verify_RemoteStatus
        else
            if ! [[ $(find /var/crash/2* -type f -size +10M) ]]; then
                LogErr "Test Failed. No file was found in /var/crash of size greater than 10M."
                SetTestStateFailed
                exit 0
            else
                UpdateSummary "Test Successful. Proper file was found."
                SetTestStateCompleted
            fi
        fi
    ;;
    suse*)
        if [[ $vm2ipv4 != "" ]]; then
            status=$(ssh -i /root/.ssh/"${SSH_PRIVATE_KEY}" -o StrictHostKeyChecking=no root@"${vm2ipv4}" "find /mnt/* -type f -size +10M; echo $?")
            Verify_RemoteStatus
        else
            Check_VMcore
        fi
    ;;
     *)
        LogErr "Test Failed. Unknown DISTRO: $DISTRO."
        SetTestStateFailed
        exit 0
    ;;
esac
