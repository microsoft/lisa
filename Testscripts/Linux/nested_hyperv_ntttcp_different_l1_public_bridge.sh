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
log_file=$logFolder/$(basename "$0").log
touch $log_file

IP_ADDR=$SERVER_IP_ADDR

if [ "$role" == "client" ]; then
    IP_ADDR=$CLIENT_IP_ADDR
fi

Start_Test()
{
    echo "server=$SERVER_IP_ADDR" >> ${CONSTANTS_FILE}
    echo "client=$CLIENT_IP_ADDR" >> ${CONSTANTS_FILE}
    echo "nicName=$NIC_NAME" >> ${CONSTANTS_FILE}

    echo $NestedUserPassword | sudo -S ip addr add $IP_ADDR/24 dev $NIC_NAME
    echo $NestedUserPassword | sudo -S ip link set $NIC_NAME up
    check_exit_status "Setup static IP address for $NIC_NAME" "exit"
    chmod a+x /home/$NestedUser/*.sh

    Log_Msg "Enable root for VM $role" $log_file
    echo $NestedUserPassword | sudo -S /home/$NestedUser/enableRoot.sh -password $NestedUserPassword
    echo $NestedUserPassword | sudo -S cp /home/$NestedUser/*.sh /root
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port 22 "hostname"

    if [ "$role" == "server" ]; then
        remote_exec -host localhost -user root -passwd $NestedUserPassword -port 22 "/root/enablePasswordLessRoot.sh"
        echo $NestedUserPassword | sudo -S md5sum /root/.ssh/id_rsa > /root/servermd5sum.log
        echo $NestedUserPassword | sudo -S cp /root/sshFix.tar /tmp
    else
        echo $NestedUserPassword | sudo -S rm -rf /root/sshFix.tar
        Log_Msg "remote_copy -host $SERVER_IP_ADDR -user $NestedUser -passwd $NestedUserPassword -port 22 -filename sshFix.tar -remote_path '/tmp' -cmd get" $log_file
        remote_copy -host $SERVER_IP_ADDR -user $NestedUser -passwd $NestedUserPassword -port 22 -filename "sshFix.tar" -remote_path "/tmp" -cmd get
        echo $NestedUserPassword | sudo -S cp -fR /home/$NestedUser/sshFix.tar /root/sshFix.tar
        remote_exec -host localhost -user root -passwd $NestedUserPassword -port 22 "/root/enablePasswordLessRoot.sh"
        echo $NestedUserPassword | sudo -S md5sum /root/.ssh/id_rsa > /root/clientmd5sum.log
    fi

    if [ "$role" == "client" ]; then
        Log_Msg "Start to run perf_ntttcp.sh on nested client VM" $log_file
        remote_exec -host localhost -user root -passwd $NestedUserPassword -port 22 "/root/perf_ntttcp.sh > ntttcpConsoleLogs"
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
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port 22 "mv /root/report.log /home/${NestedUser}"
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port 22 "mv /root/ntttcpTest.log /home/${NestedUser}"
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port 22 "mv /root/ntttcpConsoleLogs /home/${NestedUser}"
    check_exit_status "Get the NTTTCP report" "exit"
}

Update_Test_State $ICA_TESTRUNNING
Start_Test
Update_Test_State $ICA_TESTCOMPLETED
