#!/bin/bash
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# This script will run DPDk basic testpmd command in different PMDs and check failures.
# To run this script constants.sh details must.
#
########################################################################################################

HOMEDIR=$(pwd)
LOGDIR="${HOMEDIR}/DpdkTestPmdLogs"
CONSTANTS_FILE="./constants.sh"
UTIL_FILE="./utils.sh"
DPDK_UTIL_FILE="./dpdkUtils.sh"
FAILSAFE_FILE="./failsafe.sh"

[ -e $CONSTANTS_FILE ] || {
	echo "ERROR: unable to source ${CONSTANTS_FILE}!"
	echo "TestAborted" > state.txt
	exit 1
}

. ${UTIL_FILE} || {
	echo "ERROR: unable to source ${UTIL_FILE}!"
	echo "TestAborted" > state.txt
	exit 2
}
. ${DPDK_UTIL_FILE} || {
	echo "ERROR: unable to source ${DPDK_UTIL_FILE}!"
	echo "TestAborted" > state.txt
	exit 2
}

# Source constants file and initialize most common variables
UtilsInit

LogMsg "*********INFO: Script execution started********"
clientIPs=($(hostname -I))
if [[ ${clientIPs[1]} == "" ]] || [[ ${clientIPs[2]} == "" ]];
then
	LogMsg "The eth1 or eth2 doesn't have IP. Run dhclient to get IP."
	dhclient eth1 eth2
	sleep 5
	clientIPs=($(hostname -I))
else
	LogMsg "The eth1 and eth2 have IPs. Collect them for test."
fi
echo -e "client=${clientIPs[0]}\nserver=${clientIPs[0]}" >> ${CONSTANTS_FILE}
echo -e "clientNIC1ip=${clientIPs[1]}\nclientNIC2ip=${clientIPs[2]}" >> ${CONSTANTS_FILE}
. ${CONSTANTS_FILE}
LogMsg "client-vm : eth0 : ${client} : eth1 : ${clientNIC1ip} eth2 : ${clientNIC2ip}"

function checkCmdExitStatus ()
{
	exit_status=$?
	cmd=$1
	if [ $exit_status -ne 0 ]; then
		echo "$cmd: FAILED (exit code: $exit_status)"
		SetTestStateAborted
		exit $exit_status
	else
		echo "$cmd: SUCCESS"
	fi
}

runTestPmd()
{
	pmd=$1
	LogMsg "*********INFO: Starting TestPmd test execution with ${pmd} PMD*********"

	local dpdk_version=$(Get_DPDK_Version "${LIS_HOME}/${DPDK_DIR}")
	local pci_param="-w ${bus_info}"
	local dpdk_version_changed="20.11"
	if [[ ! $(printf "${dpdk_version_changed}\n${dpdk_version}" | sort -V | head -n1) == "${dpdk_version}" ]]; then
		pci_param="-a ${bus_info}"
	fi

	case "$pmd" in
		mlx*)
			vdev=""
			;;
		vdev_netvsc)
			vdev="--vdev net_vdev_netvsc0,iface=eth1,force=1"
			;;
		netvsc)
			vdev=""
			DEV_UUID=$(basename $(readlink /sys/class/net/eth1/device))
			NET_UUID="f8615163-df3e-46c5-913f-f2d2f965ed0e"
			modprobe uio_hv_generic
			echo $NET_UUID > /sys/bus/vmbus/drivers/uio_hv_generic/new_id
			echo $DEV_UUID > /sys/bus/vmbus/drivers/hv_netvsc/unbind
			echo $DEV_UUID > /sys/bus/vmbus/drivers/uio_hv_generic/bind
			;;
		tap)
			vdev="--vdev=net_tap0,iface=eth1,force=1"
			;;
		failsafe)
			curl $failsafeUrl > $FAILSAFE_FILE
			[[ $? == 0 ]] || {
				LogErr "ERROR: Cannot download $failsafeUrl!"
				exitcode=1
				return 1
			}
			mac=$(cat /sys/class/net/eth1/address)
			chmod +x ${FAILSAFE_FILE}
			vdev='$('${FAILSAFE_FILE}' '${mac}')'
			;;
		*)
			LogMsg "Not supported PMD $pmd. Abort."
			SetTestStateAborted
			exit 0
			;;
	esac
	LogMsg "TestPmd is starting with ${pmd} PMD"

	testpmd_cmd="dpdk-testpmd"
	which $testpmd_cmd > /dev/null 2>&1 || testpmd_cmd="testpmd"
	which $testpmd_cmd > /dev/null 2>&1 || {
		LogErr "ERROR: No dpdk testpmd command found. Exit!"
		SetTestStateAborted
		exit 0
	}
	cmd="echo 'stop' | $testpmd_cmd -l 0-1 ${pci_param} ${vdev} -- -i --port-topology=chained --nb-cores 1"
	LogMsg "$cmd"
	eval "$cmd" > $LOGDIR/$pmd.log 2>&1
	checkCmdExitStatus "TestPmd with ${pmd} execution"
	output=$(grep -iE -w 'err.*|fail.*|cannot.*|fatal.*' $LOGDIR/$pmd.log | grep -v failsafe)
	if [[ $? == 0 ]];then
		LogErr "ERROR: Unexpected logs are found in $pmd PMD:"
		LogMsg "$output"
		cat $LOGDIR/$pmd.log >> ./TestExecutionError.log
		exitcode=1
	fi
}


LogMsg "*********INFO: Starting DPDK Setup execution*********"
DPDK_DIR="dpdk"
LogMsg "Initial DPDK source directory: ${DPDK_DIR}"

./dpdkSetup.sh
checkCmdExitStatus "DPDK Setup"

# Start testpmd execution
SetTestStateRunning
mkdir -p $LOGDIR
IFS=',' read -r -a pmd_array <<< "$pmds"
exitcode=0
eth1_vfname=$(ip addr|grep 'master eth1'|awk -F ': ' '{print $2}')
bus_info=$(ethtool -i $eth1_vfname|grep bus-info|awk '{print $2}')
for pmd in ${pmd_array[@]};do
	runTestPmd $pmd
done
if [ $exitcode -eq 0 ];then
	SetTestStateCompleted
else
	SetTestStateFailed
fi
LogMsg "*********INFO: DPDK TestPmd script execution reach END. Completed !!!*********"
