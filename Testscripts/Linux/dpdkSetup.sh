#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# This script will do setup huge pages
# and DPDK installation on client and server machines.

UTIL_FILE="./utils.sh"
DPDK_UTIL_FILE="./dpdkUtils.sh"

# Source utils.sh
. ${UTIL_FILE} || {
	echo "ERROR: unable to source ${UTIL_FILE}!"
	echo "TestAborted" > state.txt
	exit 0
}

. ${DPDK_UTIL_FILE} || {
	echo "ERROR: unable to source ${DPDK_UTIL_FILE}!"
	echo "TestAborted" > state.txt
	exit 0
}

# Source constants file and initialize most common variables
UtilsInit

# Script start from here

LogMsg "*********INFO: Script execution Started********"
echo "server-vm : eth0 : ${server} : eth1 : ${serverNIC1ip} eth2 : ${serverNIC2ip}"
echo "client-vm : eth0 : ${client} : eth1 : ${clientNIC1ip} eth2 : ${clientNIC2ip}"

LogMsg "*********INFO: Starting Huge page configuration*********"
LogMsg "INFO: Configuring huge pages on client ${client}..."
Hugepage_Setup "${client}"

LogMsg "*********INFO: Starting setup & configuration of DPDK*********"
LogMsg "INFO: Installing DPDK on client ${client}..."
Install_Dpdk "${client}" "${clientNIC1ip}" "${serverNIC1ip}"

if [[ ${client} == ${server} ]];
then
	LogMsg "Skip DPDK setup on server"
else
	LogMsg "INFO: Configuring huge pages on server ${server}..."
	Hugepage_Setup "${server}"
	LogMsg "INFO: Installing DPDK on server ${server}..."
	Install_Dpdk "${server}" "${serverNIC1ip}" "${clientNIC1ip}"
fi

SetTestStateCompleted
LogMsg "*********INFO: DPDK setup completed*********"
