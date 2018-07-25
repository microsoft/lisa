#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# nested_kvm_ntttcp_private_bridge.sh
# Description:
#   This script runs ntttcp test on two nested VMs on same L1 guest connected with private bridge
#
#######################################################################

. ./azuremodules.sh
. ./constants.sh

while echo $1 | grep -q ^-; do
   declare $( echo $1 | sed "s/^-//" )=$2
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

CLIENT_IMAGE="nestedclient.qcow2"
SERVER_IMAGE="nestedserver.qcow2"
CLIENT_HOST_FWD_PORT=60022
SERVER_HOST_FWD_PORT=60023
BR_NAME="br0"
BR_ADDR="192.168.1.10"
CLIENT_IP_ADDR="192.168.1.11"
SERVER_IP_ADDR="192.168.1.12"
CLIENT_TAP="tap1"
SERVER_TAP="tap2"
NIC_NAME="ens4"

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

log_msg() {
    echo `date "+%b %d %Y %T"` : "$1" >> $logFolder/`basename "$0"`.log
}

update_test_state() {
    echo "$1" > $logFolder/state.txt
}

remote_exec_wrapper() {
    user_name=$1
    port=$2
    cmd=$3

    remote_exec -host localhost -user $user_name -passwd $NestedUserPassword -port $port $cmd
}

remote_copy_wrapper() {
    user_name=$1
    port=$2
    file_name=$3
    cmd=$4

    path="/home/$user_name"
    if [ $user_name == "root" ]; then
        path="/root"
    fi

    remote_copy -host localhost -user $user_name -passwd $NestedUserPassword -port $port \
        -filename $file_name -remote_path $path -cmd $cmd
}

install_dependencies() {
    update_repos
    install_package "qemu-kvm"
    lsmod | grep "kvm_intel"
    check_exit_status "Install KVM" "log_msg"
    distro=$(detect_linux_ditribution)
    if [ $distro == "centos" ] || [ $distro == "rhel" ] || [ $distro == "oracle" ]; then
        log_msg "Install epel repository"
        install_epel
        log_msg "Install qemu-system-x86"
        install_package "qemu-system-x86"
    fi
    which qemu-system-x86_64
    check_exit_status "Find qemu-system-x86_64" "log_msg"
}

get_image_files() {
    log_msg "Downloading $NestedImageUrl..."
    curl -o $CLIENT_IMAGE $NestedImageUrl
    check_exit_status "Download image from $NestedImageUrl" "log_msg"
    cp $CLIENT_IMAGE $SERVER_IMAGE
}

setup_bridge() {
    ip link show $BR_NAME
    if [ $? -eq 0 ]; then
        log_msg "Bridge $BR_NAME is already up"
        return
    fi
    log_msg "Setting up bridge $BR_NAME"
    ip link add $BR_NAME type bridge
    ifconfig $BR_NAME $BR_ADDR netmask 255.255.255.0 up
    check_exit_status "Setup bridge $BR_NAME" "log_msg"
}

setup_tap() {
    tap_name=$1
    ip link show $tap_name
    if [ $? -eq 0 ]; then
        log_msg "Tap $tap_name is already up"
        return
    fi
    log_msg "Setting up tap $tap_name"
    ip tuntap add $tap_name mode tap user `whoami` multi_queue
    ip link set $tap_name up
    ip link set $tap_name master br0
    check_exit_status "Setup tap $tap_name" "log_msg"
}

start_nested_vm() {
    image_name=$1
    tap_name=$2
    host_fwd_port=$3
    ip_addr=$4
    mac_addr1=$(generate_random_mac_addr)
    mac_addr2=$(generate_random_mac_addr)

    log_msg "Start the nested VM: $image_name"
    log_msg "qemu-system-x86_64 -cpu host -smp $NestedCpuNum -m $NestedMemMB -hda $image_name \
        -device $NestedNetDevice,netdev=net0,mac=$mac_addr1 -netdev user,id=net0,hostfwd=tcp::$host_fwd_port-:22 \
        -device $NestedNetDevice,netdev=net1,mac=$mac_addr2,mq=on,vectors=10 \
        -netdev tap,id=net1,ifname=$tap_name,script=no,vhost=on,queues=4 -display none -enable-kvm &"
    qemu-system-x86_64 -cpu host -smp $NestedCpuNum -m $NestedMemMB -hda $image_name \
        -device $NestedNetDevice,netdev=net0,mac=$mac_addr1 -netdev user,id=net0,hostfwd=tcp::$host_fwd_port-:22 \
        -device $NestedNetDevice,netdev=net1,mac=$mac_addr2,mq=on,vectors=10 \
        -netdev tap,id=net1,ifname=$tap_name,script=no,vhost=on,queues=4 -display none -enable-kvm &

    log_msg "Wait for the nested VM to boot up ..."
    sleep 10
    retry_times=20
    exit_status=1
    while [ $exit_status -ne 0 ] && [ $retry_times -gt 0 ];
    do
        retry_times=$(expr $retry_times - 1)
        if [ $retry_times -eq 0 ]; then
            log_msg "Timeout to connect to the nested VM"
            update_test_state $ICA_TESTFAILED
            exit 0
        else
           sleep 10
           log_msg "Try to connect to the nested VM, left retry times: $retry_times"
           remote_copy_wrapper $NestedUser $host_fwd_port "./enableRoot.sh" "put"
           exit_status=$?
        fi
    done
    if [ $exit_status -ne 0 ]; then
        update_test_state $ICA_TESTFAILED
        exit 0
    fi
    remote_copy_wrapper $NestedUser $host_fwd_port "./enablePasswordLessRoot.sh" "put"
    remote_copy_wrapper $NestedUser $host_fwd_port "./perf_ntttcp.sh" "put"
    remote_exec_wrapper $NestedUser $host_fwd_port "chmod a+x /home/$NestedUser/*.sh"
    remote_exec_wrapper $NestedUser $host_fwd_port "echo $NestedUserPassword | sudo -S /home/$NestedUser/enableRoot.sh -password $NestedUserPassword"
    check_exit_status "Enable root for VM $image_name" "log_msg"

    remote_exec_wrapper "root" $host_fwd_port "cp /home/$NestedUser/*.sh /root"
}

prepare_client() {
    setup_tap $CLIENT_TAP
    start_nested_vm $CLIENT_IMAGE $CLIENT_TAP $CLIENT_HOST_FWD_PORT $CLIENT_IP_ADDR
    remote_exec_wrapper "root" $CLIENT_HOST_FWD_PORT "rm -rf /root/sshFix"
    remote_exec_wrapper "root" $CLIENT_HOST_FWD_PORT "/root/enablePasswordLessRoot.sh"
    remote_copy_wrapper "root" $CLIENT_HOST_FWD_PORT "sshFix.tar" "get"
    check_exit_status "Download key from the client VM" "log_msg"

    remote_exec_wrapper "root" $CLIENT_HOST_FWD_PORT "md5sum /root/.ssh/id_rsa > /root/clientmd5sum.log"
    remote_copy_wrapper "root" $CLIENT_HOST_FWD_PORT "clientmd5sum.log" "get"

    echo "server=$SERVER_IP_ADDR" >> ./constants.sh
    echo "client=$CLIENT_IP_ADDR" >> ./constants.sh
    echo "nicName=$NIC_NAME" >> ./constants.sh
    remote_copy_wrapper "root" $CLIENT_HOST_FWD_PORT "./constants.sh" "put"
    log_msg "Reboot the nested client VM"
    remote_exec_wrapper "root" $CLIENT_HOST_FWD_PORT "reboot"
    bring_up_nic_with_private_ip $CLIENT_IP_ADDR $CLIENT_HOST_FWD_PORT
}

prepare_server() {
    setup_tap $SERVER_TAP
    start_nested_vm $SERVER_IMAGE $SERVER_TAP $SERVER_HOST_FWD_PORT $SERVER_IP_ADDR
    remote_copy_wrapper "root" $SERVER_HOST_FWD_PORT "./sshFix.tar" "put"
    check_exit_status "Copy key to the server VM" "log_msg"

    remote_exec_wrapper "root" $SERVER_HOST_FWD_PORT "/root/enablePasswordLessRoot.sh"
    remote_exec_wrapper "root" $SERVER_HOST_FWD_PORT "md5sum /root/.ssh/id_rsa > /root/servermd5sum.log"
    remote_copy_wrapper "root" $SERVER_HOST_FWD_PORT "servermd5sum.log" "get"
    log_msg "Reboot the nested server VM"
    remote_exec_wrapper "root" $SERVER_HOST_FWD_PORT "reboot"
    bring_up_nic_with_private_ip $SERVER_IP_ADDR $SERVER_HOST_FWD_PORT
}

prepare_nested_vms() {
    prepare_client
    prepare_server
    client_md5sum=$(cat ./clientmd5sum.log)
    server_md5sum=$(cat ./servermd5sum.log)

    if [[ $client_md5sum == $server_md5sum ]]; then
        log_msg "md5sum check success for .ssh/id_rsa"
    else
        log_msg "md5sum check failed for .ssh/id_rsa"
        update_test_state $ICA_TESTFAILED
        exit 1
    fi   
}

bring_up_nic_with_private_ip() {
    ip_addr=$1
    host_fwd_port=$2
    retry_times=20
    exit_status=1
    while [ $exit_status -ne 0 ] && [ $retry_times -gt 0 ];
    do
        retry_times=$(expr $retry_times - 1)
        if [ $retry_times -eq 0 ]; then
            log_msg "Timeout to connect to the nested VM"
            update_test_state $ICA_TESTFAILED
            exit 0
        else
           sleep 10
           log_msg "Try to bring up the nested VM NIC with private IP, left retry times: $retry_times"
           remote_exec_wrapper "root" $host_fwd_port "ifconfig $NIC_NAME $ip_addr netmask 255.255.255.0 up"
           exit_status=$?
        fi
    done
    if [ $exit_status -ne 0 ]; then
        update_test_state $ICA_TESTFAILED
        exit 1
    fi
}

run_ntttcp_on_client() {
    log_msg "Start to run perf_ntttcp.sh on nested client VM"
    remote_exec_wrapper "root" $CLIENT_HOST_FWD_PORT "/root/perf_ntttcp.sh > ntttcpConsoleLogs"
}

collect_logs() {
    log_msg "Finished running perf_ntttcp.sh, start to collect logs"
    remote_exec_wrapper "root" $CLIENT_HOST_FWD_PORT "mv ./ntttcp-test-logs ./ntttcp-test-logs-sender"
    remote_exec_wrapper "root" $CLIENT_HOST_FWD_PORT "tar -cf ./ntttcp-test-logs-sender.tar ./ntttcp-test-logs-sender"
    remote_copy_wrapper "root" $CLIENT_HOST_FWD_PORT "./azuremodules.sh" "put"
    remote_exec_wrapper "root" $CLIENT_HOST_FWD_PORT ". ./azuremodules.sh  && collect_VM_properties nested_properties.csv"
    remote_copy_wrapper "root" $CLIENT_HOST_FWD_PORT "ntttcp-test-logs-sender.tar" "get"
    remote_copy_wrapper "root" $CLIENT_HOST_FWD_PORT "ntttcpConsoleLogs" "get"
    remote_copy_wrapper "root" $CLIENT_HOST_FWD_PORT "ntttcpTest.log" "get"
    remote_copy_wrapper "root" $CLIENT_HOST_FWD_PORT "nested_properties.csv" "get"
    remote_exec_wrapper "root" $SERVER_HOST_FWD_PORT "mv ./ntttcp-test-logs ./ntttcp-test-logs-receiver"
    remote_exec_wrapper "root" $SERVER_HOST_FWD_PORT "tar -cf ./ntttcp-test-logs-receiver.tar ./ntttcp-test-logs-receiver"
    remote_copy_wrapper "root" $SERVER_HOST_FWD_PORT "ntttcp-test-logs-receiver.tar" "get"
    remote_copy_wrapper "root" $CLIENT_HOST_FWD_PORT "report.log" "get"
    check_exit_status "Get the NTTTCP report" "log_msg"
}

stop_nested_vms() {
    log_msg "Stop the nested VMs"
    pid=$(pidof qemu-system-x86_64)
    if [ $? -eq 0 ]; then
        log_msg "Killing pid $pid"
        kill -9 $pid
    fi
}

update_test_state $ICA_TESTRUNNING
install_dependencies
get_image_files
setup_bridge
prepare_nested_vms
run_ntttcp_on_client
collect_logs
stop_nested_vms
update_test_state $ICA_TESTCOMPLETED
