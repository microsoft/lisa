#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# nested_hyperv_ntttcp_different_l1_public_bridge.sh
# Description:
#   This script runs ntttcp test on two nested VMs on different L1 guests connected with public bridge
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
SERVER_IP_ADDR="192.168.4.20"
CLIENT_IP_ADDR="192.168.4.21"
NIC_NAME="eth1"

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
if [ -z "$NestedUser" ]; then
        echo "Please mention -NestedUser next"
        exit 1
fi
if [ -z "$NestedUserPassword" ]; then
        echo "Please mention -NestedUserPassword next"
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
log_file=$logFolder/`basename "$0"`.log
touch $log_file

IP_ADDR=$SERVER_IP_ADDR

if [ "$role" == "client" ]; then
    IP_ADDR=$CLIENT_IP_ADDR
fi

start_test()
{
    echo "server=$SERVER_IP_ADDR" >> ${CONSTANTS_FILE}
    echo "client=$CLIENT_IP_ADDR" >> ${CONSTANTS_FILE}
    echo "nicName=$NIC_NAME" >> ${CONSTANTS_FILE}

    echo $NestedUserPassword | sudo -S ifconfig $NIC_NAME up $IP_ADDR netmask 255.255.255.0 up
    check_exit_status "Setup static IP address for $NIC_NAME"
    chmod a+x /home/$NestedUser/*.sh

    log_msg "Enable root for VM $role" $log_file
    echo $NestedUserPassword | sudo -S /home/$NestedUser/enableRoot.sh -password $NestedUserPassword
    echo $NestedUserPassword | sudo -S cp /home/$NestedUser/*.sh /root 
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port 22 "hostname"

    if [ "$role" == "server" ]; then
        remote_exec -host localhost -user root -passwd $NestedUserPassword -port 22 "/root/enablePasswordLessRoot.sh"
        echo $NestedUserPassword | sudo -S md5sum /root/.ssh/id_rsa > /root/servermd5sum.log
        echo $NestedUserPassword | sudo -S cp /root/sshFix.tar /tmp
    else
        echo $NestedUserPassword | sudo -S rm -rf /root/sshFix.tar
		log_msg "remote_copy -host $SERVER_IP_ADDR -user $NestedUser -passwd $NestedUserPassword -port 22 -filename sshFix.tar -remote_path '/tmp' -cmd get" $log_file
        remote_copy -host $SERVER_IP_ADDR -user $NestedUser -passwd $NestedUserPassword -port 22 -filename "sshFix.tar" -remote_path "/tmp" -cmd get
        echo $NestedUserPassword | sudo -S cp -fR /home/$NestedUser/sshFix.tar /root/sshFix.tar
        remote_exec -host localhost -user root -passwd $NestedUserPassword -port 22 "/root/enablePasswordLessRoot.sh"
        echo $NestedUserPassword | sudo -S md5sum /root/.ssh/id_rsa > /root/clientmd5sum.log
    fi

    if [ "$role" == "client" ]; then
        log_msg "Start to run perf_ntttcp.sh on nested client VM" $log_file
        echo $NestedUserPassword | sudo -S /root/perf_ntttcp.sh > ntttcpConsoleLogs
        collect_logs
    fi
}

collect_logs() {
    log_msg "Finished running perf_ntttcp.sh, start to collect logs" $log_file
    echo $NestedUserPassword | sudo -S mv /root/ntttcp-${testType}-test-logs ./ntttcp-${testType}-test-logs-sender
    tar -cf ./ntttcp-test-logs-sender.tar ./ntttcp-${testType}-test-logs-sender
    collect_VM_properties nested_properties.csv

    remote_exec -host $SERVER_IP_ADDR -user root -passwd $NestedUserPassword -port 22 "mv ./ntttcp-${testType}-test-logs ./ntttcp-${testType}-test-logs-receiver"
    remote_exec -host $SERVER_IP_ADDR -user root -passwd $NestedUserPassword -port 22 "tar -cf ./ntttcp-test-logs-receiver.tar ./ntttcp-${testType}-test-logs-receiver"
    remote_copy -host $SERVER_IP_ADDR -user root -passwd $NestedUserPassword -port 22 -filename "./ntttcp-test-logs-receiver.tar" -remote_path "/root" -cmd "get" 
    echo $NestedUserPassword | sudo -S mv /root/report.log ./
    check_exit_status "Get the NTTTCP report"
}

update_test_state $ICA_TESTRUNNING
start_test
update_test_state $ICA_TESTCOMPLETED
