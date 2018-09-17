#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# nested_kvm_ntttcp_different_l1_nat.sh
# Description:
#   This script runs ntttcp test on two nested VMs on different L1 guests connected with nat
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
L1_CLIENT_IP_ADDR="192.168.5.31"
L1_SERVER_IP_ADDR="192.168.5.30"
L2_IP_ADDR="192.168.53.235"
NIC_NAME="ens4"

. ${CONSTANTS_FILE} || {
	errMsg="Error: missing ${CONSTANTS_FILE} file"
	LogMsg "${errMsg}"
	UpdateTestState $ICA_TESTABORTED
	exit 10
}
. ${UTIL_FILE} || {
	errMsg="Error: missing ${UTIL_FILE} file"
	LogMsg "${errMsg}"
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
if [ ! -z "$clientIP" ]; then
	L1_CLIENT_IP_ADDR=$clientIP
fi
if [ ! -z "$serverIP" ]; then
	L1_SERVER_IP_ADDR=$serverIP
fi
if [ "$role" == "server" ]; then
    if [ -z "$level1ClientIP" ]; then
            echo "Please mention -level1ClientIP next"
            exit 1
    fi
    if [ -z "$level1User" ]; then
            echo "Please mention -level1User next"
            exit 1
    fi
    if [ -z "$level1Password" ]; then
            echo "Please mention -level1Password next"
            exit 1
    fi
    if [ -z "$level1Port" ]; then
            echo "Please mention -level1Port next"
            exit 1
    fi
fi

touch $logFolder/state.txt
log_file=$logFolder/`basename "$0"`.log
touch $log_file

IP_ADDR=$L1_CLIENT_IP_ADDR

if [ "$role" == "server" ]; then
    IMAGE_NAME="nestedserver.qcow2"
    IP_ADDR=$L1_SERVER_IP_ADDR
fi

setup_network()
{
    log_msg "Setup network" $log_file
    ifconfig eth1 $IP_ADDR netmask 255.255.255.0 up
    check_exit_status "Setup network"
    ./nat_qemu_ifup.sh 
}

start_nested_vm_nat()
{
    image_name=$1
    host_fwd_port=$2
    mac_addr1=$(generate_random_mac_addr)
    mac_addr2=$(generate_random_mac_addr)
    log_msg "Start the nested VM: $image_name" $log_file
    log_msg "qemu-system-x86_64 -cpu host -smp $NestedCpuNum -m $NestedMemMB -hda $image_name -device $NestedNetDevice,netdev=net0,mac=$mac_addr1 -netdev user,id=net0,hostfwd=tcp::$host_fwd_port-:22 -device $NestedNetDevice,netdev=net1,mac=$mac_addr2 -netdev tap,id=net1,vhost=on,script=./nat_qemu_ifup.sh -display none -enable-kvm -daemonize" $log_file
    cmd="qemu-system-x86_64 -cpu host -smp $NestedCpuNum -m $NestedMemMB -hda $image_name -device $NestedNetDevice,netdev=net0,mac=$mac_addr1 -netdev user,id=net0,hostfwd=tcp::$host_fwd_port-:22 -device $NestedNetDevice,netdev=net1,mac=$mac_addr2 -netdev tap,id=net1,vhost=on,script=./nat_qemu_ifup.sh -display none -enable-kvm -daemonize"
	start_nested_vm -user $NestedUser -passwd $NestedUserPassword -port $host_fwd_port $cmd
	enable_root -user $NestedUser -passwd $NestedUserPassword -port $host_fwd_port

    remote_copy_wrapper $NestedUser $host_fwd_port "./enablePasswordLessRoot.sh" "put"
    remote_copy_wrapper $NestedUser $host_fwd_port "./perf_ntttcp.sh" "put"
    remote_copy_wrapper $NestedUser $host_fwd_port "./utils.sh" "put"
    remote_exec_wrapper $NestedUser $host_fwd_port "chmod a+x /home/$NestedUser/*.sh"
    remote_exec_wrapper $NestedUser $host_fwd_port "echo $NestedUserPassword | sudo -S dhclient $NIC_NAME"
    remote_exec_wrapper $NestedUser $host_fwd_port "echo $NestedUserPassword | sudo -S ip addr show $NIC_NAME | grep -Po 'inet \K[\d.]+' > nestedip"
    remote_copy_wrapper $NestedUser $host_fwd_port "nestedip" "get"
    L2_IP_ADDR=$(cat ./nestedip)

    remote_exec_wrapper $NestedUser $host_fwd_port "echo $NestedUserPassword | sudo -S /home/$NestedUser/enableRoot.sh -password $NestedUserPassword"
    check_exit_status "Enable root for VM $image_name"
    
    remote_exec_wrapper "root" $host_fwd_port "cp /home/$NestedUser/*.sh /root"
}

prepare_client()
{
    start_nested_vm_nat $IMAGE_NAME $HOST_FWD_PORT
    remote_copy_wrapper "root" $HOST_FWD_PORT "/tmp/sshFix.tar" "put"
    remote_exec_wrapper "root" $HOST_FWD_PORT "/root/enablePasswordLessRoot.sh"
    remote_exec_wrapper "root" $HOST_FWD_PORT "md5sum /root/.ssh/id_rsa > /root/clientmd5sum.log"
    remote_copy_wrapper "root" $HOST_FWD_PORT "clientmd5sum.log" "get"

    echo "client=$L2_IP_ADDR" >> ${CONSTANTS_FILE}
    echo "server=$L1_SERVER_IP_ADDR" >> ${CONSTANTS_FILE}
    echo "nicName=$NIC_NAME" >> ${CONSTANTS_FILE}
    remote_copy_wrapper "root" $HOST_FWD_PORT "${CONSTANTS_FILE}" "put"
}

prepare_server()
{
    start_nested_vm_nat $IMAGE_NAME $HOST_FWD_PORT

    remote_exec_wrapper "root" $HOST_FWD_PORT "rm -rf /root/sshFix"
    remote_exec_wrapper "root" $HOST_FWD_PORT "/root/enablePasswordLessRoot.sh"
    remote_copy_wrapper "root" $HOST_FWD_PORT "sshFix.tar" "get"
    remote_exec_wrapper "root" $HOST_FWD_PORT 'md5sum /root/.ssh/id_rsa > /root/servermd5sum.log'
    remote_copy_wrapper "root" $HOST_FWD_PORT "servermd5sum.log" "get"
    
    remote_copy -host $level1ClientIP -user $level1User -passwd $level1Password -port $level1Port -filename ./sshFix.tar -remote_path "/tmp" -cmd put
    echo "Setup iptables to route the traffic from L1 guest to L2 guest"
    
    iptables -t nat -A PREROUTING -d $L1_SERVER_IP_ADDR -p tcp -j DNAT --to $L2_IP_ADDR
    check_exit_status "New iptables forward rules"
}

prepare_nested_vms()
{
    if [ "$role" == "server" ]; then
        prepare_server
    fi
    if [ "$role" == "client" ]; then
        prepare_client
    fi
    reboot_nested_vm -user "root" -passwd $NestedUserPassword -port $HOST_FWD_PORT
    remote_exec_wrapper "root" $HOST_FWD_PORT "dhclient $NIC_NAME"
}

run_ntttcp_on_client()
{
    log_msg "Start to run perf_ntttcp.sh on nested client VM" $log_file
    remote_exec_wrapper "root" $HOST_FWD_PORT '/root/perf_ntttcp.sh > ntttcpConsoleLogs'
}

collect_logs()
{
    log_msg "Finished running perf_ntttcp.sh, start to collect logs" $log_file
    remote_exec_wrapper "root" $HOST_FWD_PORT 'mv ./ntttcp-${testType}-test-logs ./ntttcp-${testType}-test-logs-sender'
    remote_exec_wrapper "root" $HOST_FWD_PORT 'tar -cf ./ntttcp-test-logs-sender.tar ./ntttcp-${testType}-test-logs-sender'
    remote_exec_wrapper "root" $HOST_FWD_PORT  ". ./utils.sh && collect_VM_properties nested_properties.csv"
    remote_copy_wrapper "root" $HOST_FWD_PORT "ntttcp-test-logs-sender.tar" "get"
    remote_copy_wrapper "root" $HOST_FWD_PORT "ntttcpConsoleLogs" "get"
    remote_copy_wrapper "root" $HOST_FWD_PORT "ntttcpTest.log" "get"
    remote_copy_wrapper "root" $HOST_FWD_PORT "nested_properties.csv" "get"
    remote_copy_wrapper "root" $HOST_FWD_PORT "report.log" "get"

    remote_exec_wrapper "root" $HOST_FWD_PORT "ssh $L1_SERVER_IP_ADDR 'mv ./ntttcp-${testType}-test-logs ./ntttcp-${testType}-test-logs-receiver'"
    remote_exec_wrapper "root" $HOST_FWD_PORT "ssh $L1_SERVER_IP_ADDR 'tar -cf ./ntttcp-test-logs-receiver.tar ./ntttcp-${testType}-test-logs-receiver'"
    remote_exec_wrapper "root" $HOST_FWD_PORT "scp root@$L1_SERVER_IP_ADDR:/root/ntttcp-test-logs-receiver.tar  ."
    remote_copy_wrapper "root" $HOST_FWD_PORT "ntttcp-test-logs-receiver.tar" "get"
}

update_test_state $ICA_TESTRUNNING
install_kvm_dependencies
download_image_files -destination_image_name $IMAGE_NAME -source_image_url $NestedImageUrl
setup_network
prepare_nested_vms
if [ "$role" == "client" ]; then
    run_ntttcp_on_client
    collect_logs
    stop_nested_vm
fi
update_test_state $ICA_TESTCOMPLETED