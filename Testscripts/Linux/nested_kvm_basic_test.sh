#!/bin/bash

#######################################################################
#
# Linux on Hyper-V and Azure Test Code, ver. 1.0.0
# Copyright (c) Microsoft Corporation
#
# All rights reserved.
# Licensed under the Apache License, Version 2.0 (the ""License"");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
#
# THIS CODE IS PROVIDED *AS IS* BASIS, WITHOUT WARRANTIES OR CONDITIONS
# OF ANY KIND, EITHER EXPRESS OR IMPLIED, INCLUDING WITHOUT LIMITATION
# ANY IMPLIED WARRANTIES OR CONDITIONS OF TITLE, FITNESS FOR A PARTICULAR
# PURPOSE, MERCHANTABLITY OR NON-INFRINGEMENT.
#
# See the Apache Version 2.0 License for specific language governing
# permissions and limitations under the License.
#
#######################################################################

#######################################################################
#
#
#
# Description:
#######################################################################

. ./azuremodules.sh
. ./constants.sh

#HOW TO PARSE THE ARGUMENTS.. SOURCE - http://stackoverflow.com/questions/4882349/parsing-shell-script-arguments
while echo $1 | grep -q ^-; do
   declare $( echo $1 | sed 's/^-//' )=$2
   shift
   shift
done

#
# Constants/Globals
#
ICA_TESTRUNNING="TestRunning"      # The test is running
ICA_TESTCOMPLETED="TestCompleted"  # The test completed successfully
ICA_TESTABORTED="TestAborted"      # Error during the setup of the test
ICA_TESTFAILED="TestFailed"        # Error occurred during the test

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

touch $logFolder/state.txt
touch $logFolder/Summary.log
touch $logFolder/nested_kvm_basic_test.sh.log

LogMsg()
{
    echo `date "+%b %d %Y %T"` : "$1" >> $logFolder/nested_kvm_basic_test.sh.log
}

UpdateTestState()
{
    echo "$1" > $logFolder/state.txt
}

ResultLog()
{
    echo "$1" > $logFolder/Summary.log
}

InstallKvm()
{
    install_package qemu-kvm
    lsmod | grep kvm_intel
    exit_status=$?
    if [ $exit_status -ne 0 ]; then
        LogMsg "Install KVM fail"
        UpdateTestState $ICA_TESTFAILED
        exit 1
    else
        LogMsg "Install KVM succeed"
    fi
}

DownloadImage()
{
    install_package wget
    wget $NestedImageUrl -O $ImageName
    exit_status=$?
    if [ $exit_status -ne 0 ]; then
        LogMsg "Download image fail: $NestedImageUrl"
        UpdateTestState $ICA_TESTFAILED
        exit 1
    else
        LogMsg "Download image succeed"
    fi
}

RunNestedVM()
{
    distro=$(detect_linux_ditribution)
    if [ $distro == "centos" ] || [ $distro == "rhel" ] || [ $distro == "oracle" ]; then
        install_epel
        install_package qemu-system-x86
    fi
    if [[ `which qemu-system-x86_64` == "" ]]; then
        LogMsg "Cannot find qemu-system-x86_64"
        UpdateTestState $ICA_TESTFAILED
        exit 1
    fi

    LogMsg "Start the nested VM"
    qemu-system-x86_64 -smp 2 -m 2048 -hda $ImageName -display none -device e1000,netdev=user.0 -netdev user,id=user.0,hostfwd=tcp::$HostFwdPort-:22 -enable-kvm &
    sleep 30
    retry_times=15
    exit_status=1
    while [ $exit_status -ne 0 ] && [ $retry_times -gt 0 ];
    do
        retry_times=$(expr $retry_times - 1)
        if [ $retry_times -eq 0 ]; then
            LogMsg "Timeout to validate the network connection of the nested VM"
            UpdateTestState $ICA_TESTFAILED
        else
           sleep 10
           LogMsg "Try to connect to the nested VM, left retry times: $retry_times"
           remote_exec -user $NestedUser -passwd $NestedUserPassword -host localhost -port $HostFwdPort "wget https://raw.githubusercontent.com/LIS/LISAv2/master/README.md"
           exit_status=$?
        fi
    done
    if [ $exit_status -eq 0 ]; then
        ResultLog "Pass"
    else
        ResultLog "Fail"
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

UpdateTestState $ICA_TESTRUNNING
InstallKvm
DownloadImage
RunNestedVM
StopNestedVM
UpdateTestState $ICA_TESTCOMPLETED
