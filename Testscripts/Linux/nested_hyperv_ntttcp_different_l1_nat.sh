#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# nested_hyperv_ntttcp_different_l1_nat.sh
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
SERVER_IP_ADDR=""
CLIENT_IP_ADDR="192.168.0.3"

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
if [ -z "$level1ClientIP" ]; then
    echo "Please mention -level1ClientIP next"
    exit 1
fi
if [ -z "$level1ServerIP" ]; then
    echo "Please mention -level1ServerIP next"
    exit 1
fi
if [ -z "$logFolder" ]; then
        logFolder="."
        echo "-logFolder is not mentioned. Using ."
else
        echo "Using Log Folder $logFolder"
fi

CLIENT_IP_ADDR=$level1ClientIP
SERVER_IP_ADDR=$level1ServerIP

touch $logFolder/state.txt
log_file=$logFolder/$(basename "$0").log
touch $log_file

Start_Test()
{
    echo "server=$SERVER_IP_ADDR" >> ${CONSTANTS_FILE}
    echo "client=$CLIENT_IP_ADDR" >> ${CONSTANTS_FILE}

    chmod a+x /home/$NestedUser/*.sh

    Log_Msg "Enable root for VM $role" $log_file
    /home/$NestedUser/enableRoot.sh -password $NestedUserPassword
    cp /home/$NestedUser/*.sh /root 

    if [ "$role" == "server" ]; then
        echo "nameserver $dns_server_ip0" >> /etc/resolv.conf
        echo "nameserver $dns_server_ip1" >> /etc/resolv.conf
        Log_Msg "Enable less root for VM $role" $log_file
        /root/enablePasswordLessRoot.sh
        md5sum /root/.ssh/id_rsa > /root/servermd5sum.log
        cp /root/sshFix.tar /tmp
    else
        echo "nameserver $dns_client_ip0" >> /etc/resolv.conf
        echo "nameserver $dns_client_ip1" >> /etc/resolv.conf
        cp /home/${NestedUser}/sshFix.tar /root/sshFix.tar
        /root/enablePasswordLessRoot.sh
        md5sum /root/.ssh/id_rsa > /root/clientmd5sum.log
    fi

    if [ "$role" == "client" ]; then
        Log_Msg "Start to run perf_ntttcp.sh on nested client VM" $log_file
        pushd /root
        /root/perf_ntttcp.sh > ntttcpConsoleLogs
        Collect_Logs
    fi
}

Collect_Logs() {
    Log_Msg "Finished running perf_ntttcp.sh, start to collect logs" $LOG_FILE
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port 22 "mv /root/ntttcp-${testType}-test-logs /home/${NestedUser}/ntttcp-${testType}-test-logs-sender"
    tar -cf ./ntttcp-test-logs-sender.tar ./ntttcp-${testType}-test-logs-sender
    collect_VM_properties nested_properties.csv
    remote_exec -host $SERVER_IP_ADDR -user root -passwd $NestedUserPassword -port 22 "mv ./ntttcp-${testType}-test-logs ./ntttcp-${testType}-test-logs-receiver"
    remote_exec -host $SERVER_IP_ADDR -user root -passwd $NestedUserPassword -port 22 "tar -cf ./ntttcp-test-logs-receiver.tar ./ntttcp-${testType}-test-logs-receiver"
    remote_copy -host $SERVER_IP_ADDR -user root -passwd $NestedUserPassword -port 22 -filename "ntttcp-test-logs-receiver.tar" -remote_path "/root" -cmd "get" 
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port 22 "mv /root/ntttcp-test-logs-receiver.tar /home/${NestedUser}"
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port 22 "mv /root/ntttcp-test-logs-sender.tar /home/${NestedUser}"
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port 22 "mv /root/report.log /home/${NestedUser}"
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port 22 "mv /root/ntttcpTest.log /home/${NestedUser}"
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port 22 "mv /root/ntttcpConsoleLogs /home/${NestedUser}"
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port 22 "mv /root/nested_properties.csv /home/${NestedUser}"
    check_exit_status "Get the NTTTCP report"
}


Update_Test_State $ICA_TESTRUNNING
Start_Test
pushd /home/${NestedUser}
Update_Test_State $ICA_TESTCOMPLETED
