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
# nested_kvm_ntttcp_private_bridge.sh
# Author : Liz Zhang <lizzha@microsoft.com>
#
# Description:
#   This script runs ntttcp test on two nested VMs on same L1 guest connected with private bridge
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

#
# Constants/Globals
#
ICA_TESTRUNNING="TestRunning"      # The test is running
ICA_TESTCOMPLETED="TestCompleted"  # The test completed successfully
ICA_TESTABORTED="TestAborted"      # Error during the setup of the test
ICA_TESTFAILED="TestFailed"        # Error occurred during the test

ClientImage="nestedclient.qcow2"
ServerImage="nestedserver.qcow2"
ClientHostFwdPort=60022
ServerHostFwdPort=60023
BrName="br0"
BrAddr="192.168.1.10"
ClientIpAddr="192.168.1.11"
ServerIpAddr="192.168.1.12"
ClientTap="tap1"
ServerTap="tap2"

if [ -z "$NestedImageUrl" ]; then
        echo "Please mention -NestedImageUrl next"
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
if [ -z "$NestedCpuNum" ]; then
        echo "Please mention -NestedCpuNum next"
        exit 1
fi
if [ -z "$NestedMemMB" ]; then
        echo "Please mention -NestedMemMB next"
        exit 1
fi
if [ -z "$NestedNetDevice" ]; then
        echo "Please mention -NestedNetDevice next"
        exit 1
fi
if [ -z "$testDuration" ]; then
        echo "Please mention -testDuration next"
        exit 1
fi
if [ -z "$testConnections" ]; then
        echo "Please mention -testConnections next"
        exit 1
fi
if [ -z "$logFolder" ]; then
        logFolder="."
        echo "-logFolder is not mentioned. Using ."
else
        echo "Using Log Folder $logFolder"
fi

touch $logFolder/state.txt
touch $logFolder/`basename "$0"`.log

LogMsg()
{
    echo `date "+%b %d %Y %T"` : "$1" >> $logFolder/`basename "$0"`.log
}

UpdateTestState()
{
    echo "$1" > $logFolder/state.txt
}

InstallDependencies()
{
    update_repos
    install_package qemu-kvm
    lsmod | grep kvm_intel
    exit_status=$?
    if [ $exit_status -ne 0 ]; then
        LogMsg "Failed to install KVM"
        UpdateTestState $ICA_TESTFAILED
        exit 0
    else
        LogMsg "Install KVM succeed"
    fi
    distro=$(detect_linux_ditribution)
    if [ $distro == "centos" ] || [ $distro == "rhel" ] || [ $distro == "oracle" ]; then
        LogMsg "Install epel repository"
        install_epel
        LogMsg "Install qemu-system-x86"
        install_package qemu-system-x86
    fi
    which qemu-system-x86_64
    if [ $? -ne 0 ]; then
        LogMsg "Cannot find qemu-system-x86_64"
        UpdateTestState $ICA_TESTFAILED
        exit 0
    fi
}

GetImageFiles()
{
    LogMsg "Downloading $NestedImageUrl..."
    temp_image="nested.qcow2"
    curl -o $temp_image $NestedImageUrl
    exit_status=$?
    if [ $exit_status -ne 0 ]; then
        LogMsg "Download image fail: $NestedImageUrl"
        UpdateTestState $ICA_TESTFAILED
        exit 0
    else
        LogMsg "Download image succeed"
    fi
    cp $temp_image $ClientImage
    cp $temp_image $ServerImage
}

SetupBridge()
{
    LogMsg "Setup bridge $BrName"
    ip link add $BrName type bridge
    ifconfig $BrName $BrAddr netmask 255.255.255.0 up
    check_exit_status "Setup bridge $BrName"
}

SetupTap()
{
    tap_name=$1
    LogMsg "Setup tap $tap_name"
    ip tuntap add $tap_name mode tap user `whoami` multi_queue
    ip link set $tap_name up
    ip link set $tap_name master br0
    check_exit_status "Setup tap $tap_name"
}

StartNestedVM()
{
    image_name=$1
    tap_name=$2
    host_fwd_port=$3
    ip_addr=$4
    mac_addr1="52:54:00:a1:$(dd if=/dev/urandom bs=512 count=1 2>/dev/null | md5sum | sed 's/^\(..\)\(..\).*$/\1:\2/')"
    mac_addr2="52:54:00:a2:$(dd if=/dev/urandom bs=512 count=1 2>/dev/null | md5sum | sed 's/^\(..\)\(..\).*$/\1:\2/')"
    LogMsg "Start the nested VM: $image_name"
    LogMsg "qemu-system-x86_64 -cpu host -smp $NestedCpuNum -m $NestedMemMB -hda $image_name -device $NestedNetDevice,netdev=net0,mac=$mac_addr1 -netdev user,id=net0,hostfwd=tcp::$host_fwd_port-:22 \
        -device $NestedNetDevice,netdev=net1,mac=$mac_addr2,mq=on,vectors=10 -netdev tap,id=net1,ifname=$tap_name,script=no,vhost=on,queues=4 -display none -enable-kvm &"
    qemu-system-x86_64 -cpu host -smp $NestedCpuNum -m $NestedMemMB -hda $image_name -device $NestedNetDevice,netdev=net0,mac=$mac_addr1 -netdev user,id=net0,hostfwd=tcp::$host_fwd_port-:22 \
        -device $NestedNetDevice,netdev=net1,mac=$mac_addr2,mq=on,vectors=10 -netdev tap,id=net1,ifname=$tap_name,script=no,vhost=on,queues=4 -display none -enable-kvm &
    LogMsg "Wait for the nested VM to boot up ..."
    sleep 10
    retry_times=20
    exit_status=1
    while [ $exit_status -ne 0 ] && [ $retry_times -gt 0 ];
    do
        retry_times=$(expr $retry_times - 1)
        if [ $retry_times -eq 0 ]; then
            LogMsg "Timeout to connect to the nested VM"
            UpdateTestState $ICA_TESTFAILED
            exit 0
        else
           sleep 10
           LogMsg "Try to connect to the nested VM, left retry times: $retry_times"
           remote_copy -host localhost -user $NestedUser -passwd $NestedUserPassword -port $host_fwd_port -filename ./enableRoot.sh -remote_path /home/$NestedUser -cmd put
           exit_status=$?
        fi
    done
    if [ $exit_status -ne 0 ]; then
        UpdateTestState $ICA_TESTFAILED
        exit 0
    fi
    remote_copy -host localhost -user $NestedUser -passwd $NestedUserPassword -port $host_fwd_port -filename ./enablePasswordLessRoot.sh -remote_path /home/$NestedUser -cmd put
    remote_copy -host localhost -user $NestedUser -passwd $NestedUserPassword -port $host_fwd_port -filename ./perf_ntttcp.sh -remote_path /home/$NestedUser -cmd put
    remote_exec -host localhost -user $NestedUser -passwd $NestedUserPassword -port $host_fwd_port "chmod a+x /home/$NestedUser/*.sh"
    remote_exec -host localhost -user $NestedUser -passwd $NestedUserPassword -port $host_fwd_port "echo $NestedUserPassword | sudo -S /home/$NestedUser/enableRoot.sh -password $NestedUserPassword"
    if [ $? -eq 0 ]; then
        LogMsg "Root enabled for VM: $image_name"
    else
        LogMsg "Failed to enable root for VM: $image_name"
        UpdateTestState $ICA_TESTFAILED
        exit 0
    fi
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port $host_fwd_port "cp /home/$NestedUser/*.sh /root"
}

PrepareClient()
{
    SetupTap $ClientTap
    StartNestedVM $ClientImage $ClientTap $ClientHostFwdPort $ClientIpAddr
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port $ClientHostFwdPort "rm -rf /root/sshFix"
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port $ClientHostFwdPort "/root/enablePasswordLessRoot.sh"
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $ClientHostFwdPort -filename sshFix.tar -remote_path "/root/" -cmd get
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port $ClientHostFwdPort 'md5sum /root/.ssh/id_rsa > /root/clientmd5sum.log'
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $ClientHostFwdPort -filename clientmd5sum.log -remote_path "/root/" -cmd get

    echo "server=$ServerIpAddr" >> ./constants.sh
    echo "client=$ClientIpAddr" >> ./constants.sh
    echo "nicName=ens4" >> ./constants.sh
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $ClientHostFwdPort -filename ./constants.sh -remote_path "/root/" -cmd put
    LogMsg "Reboot the nested client VM"
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port $ClientHostFwdPort 'reboot'
    BringUpNicWithPrivateIp $ClientIpAddr $ClientHostFwdPort
}

PrepareServer()
{
    SetupTap $ServerTap
    StartNestedVM $ServerImage $ServerTap $ServerHostFwdPort $ServerIpAddr
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $ServerHostFwdPort -filename ./sshFix.tar -remote_path "/root/" -cmd put
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port $ServerHostFwdPort "/root/enablePasswordLessRoot.sh"
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port $ServerHostFwdPort 'md5sum /root/.ssh/id_rsa > /root/servermd5sum.log'
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $ServerHostFwdPort -filename servermd5sum.log -remote_path "/root/" -cmd get
    LogMsg "Reboot the nested server VM"
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port $ServerHostFwdPort 'reboot'
    BringUpNicWithPrivateIp $ServerIpAddr $ServerHostFwdPort
}

PrepareNestedVMs()
{
    PrepareClient
    PrepareServer
    client_md5sum=`cat ./clientmd5sum.log`
    server_md5sum=`cat ./servermd5sum.log`

    if [[ $client_md5sum == $server_md5sum ]]; then
        LogMsg "md5sum check success for .ssh/id_rsa"
    else
        LogMsg "md5sum check failed for .ssh/id_rsa"
        UpdateTestState $ICA_TESTFAILED
        exit 0
    fi   
}

BringUpNicWithPrivateIp()
{
    ip_addr=$1
    host_fwd_port=$2
    retry_times=20
    exit_status=1
    while [ $exit_status -ne 0 ] && [ $retry_times -gt 0 ];
    do
        retry_times=$(expr $retry_times - 1)
        if [ $retry_times -eq 0 ]; then
            LogMsg "Timeout to connect to the nested VM"
            UpdateTestState $ICA_TESTFAILED
            exit 0
        else
           sleep 10
           LogMsg "Try to bring up the nested VM NIC with private IP, left retry times: $retry_times"
           remote_exec -host localhost -user root -passwd $NestedUserPassword -port $host_fwd_port "ifconfig ens4 $ip_addr netmask 255.255.255.0 up"
           exit_status=$?
        fi
    done
    if [ $exit_status -ne 0 ]; then
        UpdateTestState $ICA_TESTFAILED
        exit 0
    fi
}

RunNtttcpOnClient()
{
    LogMsg "Start to run perf_ntttcp.sh on nested client VM"
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port $ClientHostFwdPort '/root/perf_ntttcp.sh > ntttcpConsoleLogs'
}

CollectLogs()
{
    LogMsg "Finished running perf_ntttcp.sh, start to collect logs"
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port $ClientHostFwdPort 'mv ./ntttcp-test-logs ./ntttcp-test-logs-sender'
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port $ClientHostFwdPort 'tar -cf ./ntttcp-test-logs-sender.tar ./ntttcp-test-logs-sender'
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $ClientHostFwdPort -filename ./azuremodules.sh -remote_path "/root/" -cmd put
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port $ClientHostFwdPort '. ./azuremodules.sh  && collect_VM_properties nested_properties.csv'
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $ClientHostFwdPort -filename ntttcp-test-logs-sender.tar -remote_path "/root/" -cmd get
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $ClientHostFwdPort -filename ntttcpConsoleLogs -remote_path "/root/" -cmd get
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $ClientHostFwdPort -filename ntttcpTest.log -remote_path "/root/" -cmd get
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $ClientHostFwdPort -filename nested_properties.csv -remote_path "/root/" -cmd get
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $ClientHostFwdPort -filename report.log -remote_path "/root/" -cmd get

    remote_exec -host localhost -user root -passwd $NestedUserPassword -port $ServerHostFwdPort 'mv ./ntttcp-test-logs ./ntttcp-test-logs-receiver'
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port $ServerHostFwdPort 'tar -cf ./ntttcp-test-logs-receiver.tar ./ntttcp-test-logs-receiver'
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $ServerHostFwdPort -filename ntttcp-test-logs-receiver.tar -remote_path "/root/" -cmd get
}

StopNestedVMs()
{
    LogMsg "Stop the nested VMs"
    pid=$(pidof qemu-system-x86_64)
    if [ $? -eq 0 ]; then
        kill -9 $pid
    fi
}

UpdateTestState $ICA_TESTRUNNING
InstallDependencies
GetImageFiles
SetupBridge
PrepareNestedVMs
RunNtttcpOnClient
CollectLogs
StopNestedVMs
UpdateTestState $ICA_TESTCOMPLETED
