#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# nested_kvm_basic_test.sh
#
# Description:
#   This script tests the basic functionality of nested VM in a Linux VM, steps:
#     1. Start a nested ubuntu VM, VM network: user mode network, with host port redirect enabled
#     2. Verify the nested VM can access public network, by running a command in the nested VM to download a public file from github
#
# Parameters:
#   -NestedImageUrl: The public url of the nested image, the image format should be qcow2
#   -NestedUser: The user name of the nested image
#   -NestedUserPassword: The user password of the nested image
#   -HostFwdPort: The host port that will redirect to the SSH port of the nested VM
#   -logFolder: The folder path for logs
#
#######################################################################

. ./azuremodules.sh
. ./constants.sh

#HOW TO PARSE THE ARGUMENTS.. SOURCE - http://stackoverflow.com/questions/4882349/parsing-shell-script-arguments
while echo $1 | grep -q ^-; do
   declare $( echo $1 | sed 's/^-//' )=$2
   shift
   shift
done

ImageName="nested.qcow2"

if [ -z "$NestedImageUrl" ]; then
        echo "Please mention -NestedImageUrl next"
        exit 1
fi
if [ -z "$HostFwdPort" ]; then
        echo "Please mention -HostFwdPort next"
        exit 1
fi
if [ -z "$NestedUser" ]; then
        echo "Please mention -NestedUser next"
        exit 1
fi
if [ -z "$NestedUserPassword" ]; then
        echo "Please mention -NestedUserPassword next"
        exit 1
fi
if [ -z "$logFolder" ]; then
        logFolder="."
        echo "-logFolder is not mentioned. Using ."
else
        echo "Using Log Folder $logFolder"
fi

touch $logFolder/TestExecution.log
touch $logFolder/TestExecutionError.log

LogMsg()
{
    echo `date "+%b %d %Y %T"` : "$1" >> $logFolder/TestExecution.log
}
LogErr()
{
    echo `date "+%b %d %Y %T"` : "$1" >> $logFolder/TestExecutionError.log
}

ResultLog()
{
    #Result can only be PASS / FAIL / Aborted
    echo "$1" > $logFolder/TestState.log
}

InstallKvm()
{
    update_repos
    install_package qemu-kvm
    lsmod | grep kvm_intel
    exit_status=$?
    if [ $exit_status -ne 0 ]; then
        LogErr "Install KVM fail"
        ResultLog  "Aborted"
        exit 0
    else
        LogMsg "Install KVM succeed"
    fi
}

DownloadImage()
{
    LogMsg "Downloading $NestedImageUrl..."
    curl -o $ImageName $NestedImageUrl
    exit_status=$?
    if [ $exit_status -ne 0 ]; then
        LogErr "Download image fail: $NestedImageUrl"
        ResultLog "Aborted"
        exit 0
    else
        LogMsg "Download image succeed"
    fi
}

RunNestedVM()
{
    distro=$(detect_linux_ditribution)
    if [ $distro == "centos" ] || [ $distro == "rhel" ] || [ $distro == "oracle" ]; then
        LogMsg "Install epel repository"
        install_epel
        LogMsg "Install qemu-system-x86"
        install_package qemu-system-x86
    fi
    which qemu-system-x86_64
    if [ $? -ne 0 ]; then
        LogErr "Cannot find qemu-system-x86_64"
        ResultLog "Aborted"
        exit 0
    fi

    LogMsg "Start the nested VM"
    qemu-system-x86_64 -smp 2 -m 2048 -hda $ImageName -display none -device e1000,netdev=user.0 -netdev user,id=user.0,hostfwd=tcp::$HostFwdPort-:22 -enable-kvm &
    LogMsg "Wait for the nested VM to boot up ..."
    sleep 10
    retry_times=24
    exit_status=1
    while [ $exit_status -ne 0 ] && [ $retry_times -gt 0 ];
    do
        retry_times=$(expr $retry_times - 1)
        if [ $retry_times -eq 0 ]; then
            LogErr "Timeout to validate the network connection of the nested VM"
            ResultLog "FAIL"
            exit 0
        else
           sleep 10
           LogMsg "Try to connect to the nested VM, left retry times: $retry_times"
           remote_exec -user $NestedUser -passwd $NestedUserPassword -host localhost -port $HostFwdPort "wget https://raw.githubusercontent.com/LIS/LISAv2/master/README.md"
           exit_status=$?
        fi
    done
    if [ $exit_status -eq 0 ]; then
        ResultLog "PASS"
        StopNestedVM
    else
        ResultLog "FAIL"
    fi
}

StopNestedVM()
{
    LogMsg "Stop the nested VM"
    pid=$(pidof qemu-system-x86_64)
    if [ $? -eq 0 ]; then
        kill -9 $pid
    fi
}

InstallKvm
DownloadImage
RunNestedVM

#Exiting with zero is important.
exit 0