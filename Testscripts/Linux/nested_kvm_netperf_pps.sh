#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# nested_kvm_netperf_pps.sh
# Description:
#   This script runs netperf test on two nested VMs on different L1 guests connected with public bridge
#
#######################################################################

UTIL_FILE="./nested_vm_utils.sh"
CONSTANTS_FILE="./constants.sh"

while echo $1 | grep -q ^-; do
   declare $( echo $1 | sed 's/^-//' )=$2
   shift
   shift
done

#
# Constants/Globals
#
IMAGE_NAME="nestedclient.qcow2"
HOST_FWD_PORT=60022
BR_NAME="br0"
BR_ADDR="192.168.4.20"
CLIENT_IP_ADDR="192.168.4.21"
SERVER_IP_ADDR="192.168.4.11"
TAP_NAME="tap0"
NIC_NAME="ens4"
IP_ADDR=$CLIENT_IP_ADDR

. ${CONSTANTS_FILE} || {
    errMsg="Error: missing ${CONSTANTS_FILE} file"
    echo "${errMsg}"
    UpdateTestState $ICA_TESTABORTED
    exit 10
}
. ${UTIL_FILE} || {
    errMsg="Error: missing ${UTIL_FILE} file"
    echo "${errMsg}"
    UpdateTestState $ICA_TESTABORTED
    exit 10
}

if [ -z "$role" ]; then
        echo "Please specify -Role next"
        exit 1
fi
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
if [ -z "$test_duration" ]; then
        echo "Please mention -test_duration next"
        exit 1
fi
if [ -z "$test_type" ]; then
        echo "Please mention -test_type next"
        exit 1
fi
if [ -z "$logFolder" ]; then
        logFolder="."
        echo "-logFolder is not mentioned. Using ."
else
        echo "Using Log Folder $logFolder"
fi
if [ "$role" == "server" ]; then
    if [ -z "$level1ClientIP" ]; then
            echo "Please mention -level1ClientIP next"
            exit 1
    fi
    if [ -z "$level1ClientUser" ]; then
            echo "Please mention -level1ClientUser next"
            exit 1
    fi
    if [ -z "$level1ClientPassword" ]; then
            echo "Please mention -level1ClientPassword next"
            exit 1
    fi
    if [ -z "$level1ClientPort" ]; then
            echo "Please mention -level1ClientPort next"
            exit 1
    fi
fi

touch $logFolder/state.txt
log_file=$logFolder/$(basename "$0").log
touch $log_file

if [ "$role" == "server" ]; then
    IMAGE_NAME="nestedserver.qcow2"
    BR_ADDR="192.168.4.10"
    IP_ADDR=$SERVER_IP_ADDR
fi

Start_Nested_VM_Public_Bridge()
{
    image_name=$1
    tap_name=$2
    host_fwd_port=$3
    mac_addr1=$(generate_random_mac_addr)
    Log_Msg "Start the nested VM: $image_name" $log_file
    Log_Msg "qemu-system-x86_64 -cpu host -smp $NestedCpuNum -m $NestedMemMB -hda $image_name -device $NestedNetDevice,netdev=net0 -netdev user,id=net0,hostfwd=tcp::$host_fwd_port-:22 -device $NestedNetDevice,netdev=net1,mac=$mac_addr1,mq=on,vectors=10 -netdev tap,id=net1,ifname=$tap_name,script=no,vhost=on,queues=4 -display none -enable-kvm -daemonize" $log_file
    cmd="qemu-system-x86_64 -cpu host -smp $NestedCpuNum -m $NestedMemMB -hda $image_name -device $NestedNetDevice,netdev=net0 -netdev user,id=net0,hostfwd=tcp::$host_fwd_port-:22 -device $NestedNetDevice,netdev=net1,mac=$mac_addr1,mq=on,vectors=10 -netdev tap,id=net1,ifname=$tap_name,script=no,vhost=on,queues=4 -display none -enable-kvm -daemonize"
    Start_Nested_VM -user $NestedUser -passwd $NestedUserPassword -port $host_fwd_port $cmd
    Enable_Root -user $NestedUser -passwd $NestedUserPassword -port $host_fwd_port

    Remote_Copy_Wrapper $NestedUser $host_fwd_port "./enablePasswordLessRoot.sh" "put"
    Remote_Copy_Wrapper $NestedUser $host_fwd_port "./perf_netperf.sh" "put"
    Remote_Copy_Wrapper $NestedUser $host_fwd_port "./utils.sh" "put"
    Remote_Exec_Wrapper $NestedUser $host_fwd_port "chmod a+x /home/$NestedUser/*.sh"
    Remote_Exec_Wrapper $NestedUser $host_fwd_port "echo $NestedUserPassword | sudo -S /home/$NestedUser/enableRoot.sh -password $NestedUserPassword"
    check_exit_status "Enable root for VM $image_name"
    Remote_Exec_Wrapper "root" $host_fwd_port "cp /home/$NestedUser/*.sh /root"
}

Prepare_Client()
{
    Setup_Tap $TAP_NAME $BR_NAME
    Start_Nested_VM_Public_Bridge $IMAGE_NAME $TAP_NAME $HOST_FWD_PORT
    Remote_Copy_Wrapper "root" $HOST_FWD_PORT "/tmp/sshFix.tar" "put"
    Remote_Exec_Wrapper "root" $HOST_FWD_PORT "/root/enablePasswordLessRoot.sh"
    Remote_Exec_Wrapper "root" $HOST_FWD_PORT "md5sum /root/.ssh/id_rsa > /root/clientmd5sum.log"
    Remote_Copy_Wrapper "root" $HOST_FWD_PORT "clientmd5sum.log" "get"

    echo "server=$SERVER_IP_ADDR" >> ${CONSTANTS_FILE}
    echo "client=$CLIENT_IP_ADDR" >> ${CONSTANTS_FILE}
    echo "test_duration=$test_duration" >> ${CONSTANTS_FILE}
    echo "test_type=$test_type" >> ${CONSTANTS_FILE}
    Remote_Copy_Wrapper "root" $HOST_FWD_PORT "${CONSTANTS_FILE}" "put"
}

Prepare_Server()
{
    Setup_Tap $TAP_NAME $BR_NAME
    Start_Nested_VM_Public_Bridge $IMAGE_NAME $TAP_NAME $HOST_FWD_PORT

    Remote_Exec_Wrapper "root" $HOST_FWD_PORT "rm -rf /root/sshFix"
    Remote_Exec_Wrapper "root" $HOST_FWD_PORT "/root/enablePasswordLessRoot.sh"
    Remote_Copy_Wrapper "root" $HOST_FWD_PORT "sshFix.tar" "get"
    Remote_Exec_Wrapper "root" $HOST_FWD_PORT 'md5sum /root/.ssh/id_rsa > /root/servermd5sum.log'
    Remote_Copy_Wrapper "root" $HOST_FWD_PORT "servermd5sum.log" "get"

    remote_copy -host $level1ClientIP -user $level1ClientUser -passwd $level1ClientPassword -port $level1ClientPort -filename ./sshFix.tar -remote_path "/tmp" -cmd put
}

Prepare_Nested_VMs()
{
    if [ "$role" == "server" ]; then
        Prepare_Server
    fi
    if [ "$role" == "client" ]; then
        Prepare_Client
    fi
    Reboot_Nested_VM -user "root" -passwd $NestedUserPassword -port $HOST_FWD_PORT
    Remote_Exec_Wrapper "root" $HOST_FWD_PORT "ip addr add $IP_ADDR/24 dev $NIC_NAME && ip link set $NIC_NAME up"
}

Run_Netperf_On_Client()
{
    Log_Msg "Start to run perf_netperf.sh on nested client VM" $log_file
    Remote_Exec_Wrapper "root" $HOST_FWD_PORT '/root/perf_netperf.sh &> netperfConsoleLogs.txt'
}

Collect_Logs()
{
    Log_Msg "Finished running perf_netperf.sh, start to collect logs" $log_file

    Remote_Exec_Wrapper "root" $HOST_FWD_PORT "scp root@$SERVER_IP_ADDR:/root/netperf-server-sar-output.txt  ."
    Remote_Exec_Wrapper "root" $HOST_FWD_PORT "scp root@$SERVER_IP_ADDR:/root/netperf-server-output.txt  ."
    Remote_Exec_Wrapper "root" $HOST_FWD_PORT  ". ./utils.sh && collect_VM_properties nested_properties.csv"
    Remote_Copy_Wrapper "root" $HOST_FWD_PORT "netperf-server-sar-output.txt" "get"
    Remote_Copy_Wrapper "root" $HOST_FWD_PORT "netperf-server-output.txt" "get"
    Remote_Copy_Wrapper "root" $HOST_FWD_PORT "TestExecution.log" "get"
    Remote_Copy_Wrapper "root" $HOST_FWD_PORT "netperfConsoleLogs.txt" "get"
    Remote_Copy_Wrapper "root" $HOST_FWD_PORT "netperf-client-sar-output.txt" "get"
    Remote_Copy_Wrapper "root" $HOST_FWD_PORT "netperf-client-output.txt" "get"
    Remote_Copy_Wrapper "root" $HOST_FWD_PORT "nested_properties.csv" "get"
}

Update_Test_State $ICA_TESTRUNNING
collect_VM_properties
Install_KVM_Dependencies
Download_Image_Files -destination_image_name $IMAGE_NAME -source_image_url $NestedImageUrl
Setup_Public_Bridge $BR_NAME $BR_ADDR
Prepare_Nested_VMs
if [ "$role" == "client" ]; then
    Run_Netperf_On_Client
    Collect_Logs
    Stop_Nested_VM
fi
Update_Test_State $ICA_TESTCOMPLETED
