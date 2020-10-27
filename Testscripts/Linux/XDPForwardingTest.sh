#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# This script starts pktgen and checks XDP_TX forwarding performance by starting xdpdump application
# in forwarding configuration on forwarder VM and checks how many packets received at the receiver interface
# by running xdpdump application in drop configuration (number of packets received == number of packets dropped).

# This script requires argument:
# 		1. packetCount: Number of packets to send from sender


nicName='eth1'
packetFwdThreshold=50

# This function is called from dpdk_install function to configure ips.
function Dpdk_Configure() {
        if [ -z "${1}" ]; then
                LogErr "ERROR: Must provide install_ip to Dpdk_Configure"
                SetTestStateAborted
                exit 1
        fi
        Testpmd_Ip_Setup "SRC" "${senderSecondIP}"
        Testpmd_Ip_Setup "DST" "${forwarderSecondIP}"
}

function convert_MAC_to_HEXArray(){
    while IFS=':' read -ra ADDR; do
        size=$((${#ADDR[@]} - 1))
        MACarr=$(printf '0x%s\n' ${ADDR[$i]})
        for i in $(seq 1 $size);
        do
            MACarr="$MACarr, $(printf '0x%s\n' ${ADDR[$i]})";
        done
    done <<< "$1"
    echo "$MACarr"
}

function configure_XDPDUMP_TX(){
    LogMsg "Configuring TX Setup"
    # new distros does not have ifconfig present by default
    LogMsg "Installing net-tools for confirming ifconfig is present in VM."
    installCommand="install_package net-tools"
    $installCommand
    ssh $forwarder  ". utils.sh && $installCommand"
    ssh $receiver ". utils.sh && $installCommand"

    get_ip_command="/sbin/ifconfig $nicName | grep 'inet' | cut -d: -f2"
    get_mac_command="/sbin/ifconfig $nicName | grep -o -E '([[:xdigit:]]{1,2}:){5}[[:xdigit:]]{1,2}'"
    forwarderIP=$((ssh $forwarder $get_ip_command) | awk '{print $2}')
    LogMsg "Forwarder IP: $forwarderIP"
    receiverIP=$((ssh $receiver $get_ip_command) | awk '{print $2}')
    LogMsg "Receiver IP: $receiverIP"
    forwarderMAC=$(ssh $forwarder $get_mac_command)
    LogMsg "Forwarder MAC: $forwarderMAC"
    receiverMAC=$(ssh $receiver $get_mac_command)
    LogMsg "Receiver MAC: $receiverMAC"

    #formatting MAC and IP address as needed in xdpdump file.
    forwarderIP1=$(echo $forwarderIP | sed "s/\./\, /g")
    receiverIP1=$(echo $receiverIP | sed "s/\./\, /g")
    forwarderMAC1=$(convert_MAC_to_HEXArray $forwarderMAC)
    receiverMAC1=$(convert_MAC_to_HEXArray $receiverMAC)
    xdpdumpFileName=bpf-samples/xdpdump/xdpdump_kern.c

    LogMsg "Updating $xdpdumpFileName file with forwarding setup on $forwarder"
    commandMACS="sed -i 's/unsigned char newethsrc \[\] = { 0x00, 0x22, 0x48, 0x4c, 0xc4, 0x4d };/unsigned char newethsrc \[\] = { ${forwarderMAC1} };/g' ${xdpdumpFileName}"
    ssh $forwarder $commandMACS
    commandMACD="sed -i 's/unsigned char newethdest \[\] = { 0x00, 0x22, 0x48, 0x4c, 0xc0, 0xfd };/unsigned char newethdest \[\] = { ${receiverMAC1} };/g' ${xdpdumpFileName}"
    ssh $forwarder $commandMACD
    LogMsg "Updated Source &  Destination MAC address in $xdpdumpFileName on $forwarder"
    commandIPS="sed -i 's/__u8 newsrc \[\] = { 10, 0, 1, 5 };/__u8 newsrc \[\] = { ${forwarderIP1} };/g' ${xdpdumpFileName}"
    ssh $forwarder $commandIPS
    commandIPD="sed -i 's/__u8 newdest \[\] = { 10, 0, 1, 4 };/__u8 newdest \[\] = { ${receiverIP1} };/g' ${xdpdumpFileName}"
    ssh $forwarder $commandIPD
    LogMsg "Updated Source &  Destination IP address in $xdpdumpFileName on $forwarder"
}

UTIL_FILE="./utils.sh"

# Source utils.sh
. ${UTIL_FILE} || {
    echo "ERROR: unable to source ${UTIL_FILE}!"
    echo "TestAborted" > state.txt
    exit 0
}

XDPUTIL_FILE="./XDPUtils.sh"

# Source XDPUtils.sh
. ${XDPUTIL_FILE} || {
    LogMsg "ERROR: unable to source ${XDPUTIL_FILE}!"
    SetTestStateAborted
    exit 0
}

DPDKUTIL_FILE="./dpdkUtils.sh"

# Source DPDKUtils.sh
. ${DPDKUTIL_FILE} || {
    LogMsg "ERROR: unable to source ${DPDKUTIL_FILE}!"
    SetTestStateAborted
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit
# Script start from here
# check for parameters
if [ -z "${1}" ]; then
	LogErr "Please give arg: test_duration"
	SetTestStateAborted
	exit 0
fi
test_duration=$1

LogMsg "*********INFO: Script execution Started********"
LogMsg "forwarder : ${forwarder}"
LogMsg "receiver : ${receiver}"
LogMsg "nicName: ${nicName}"
bash ./XDPDumpSetup.sh ${forwarder} ${nicName}
check_exit_status "XDPDumpSetup on ${forwarder}" "exit"
SetTestStateRunning
bash ./XDPDumpSetup.sh ${receiver} ${nicName}
check_exit_status "XDpDUMPSetup on ${receiver}" "exit"
SetTestStateRunning
configure_XDPDUMP_TX

LogMsg "XDP Setup Completed"
# As LIS_HOME/constants.sh variables are not present at /root. It is needed by dpdk scripts.
cp ${LIS_HOME}/constants.sh /root/constants.sh

# Huge Page Setup
Install_Dpdk "${sender}"
check_exit_status "DPDK Setup on ${sender}" "exit"
Hugepage_Setup "${sender}"
check_exit_status "Huge page Setup on ${sender}" "exit"
Modprobe_Setup "${sender}"
check_exit_status "Modprobe setup on ${sender}"
LogMsg "DPDK Setup is Completed"

# Configure XDP_TX on Forwarder
LogMsg "Build XDPDump with TX Action on ${forwarder}"
ssh ${forwarder} "cd bpf-samples/xdpdump && make clean && CFLAGS='-D __TX_FWD__ -D __PERF__ -I../libbpf/src/root/usr/include' make"
check_exit_status "Build xdpdump with TX Action on ${forwarder}"
# Configure XDP_DROP on receiver
LogMsg "Build XDPDump with DROP Action on ${receiver}"
ssh ${receiver} "cd bpf-samples/xdpdump && make clean && CFLAGS='-D __PERF_DROP__ -D __PERF__ -I../libbpf/src/root/usr/include' make"
check_exit_status "Build xdpdump with DROP Action on ${receiver}"

echo "test_type,data_path,sender_pps,packets_sent,packets_forwarded,packets_received,cpu_ideal" > report.csv
pps_array=()
packets_received=()
for mode in ${modes[*]}; do
	LogMsg "Running Mode: $mode"
	# Calculate packet drops before tests
	packetDropBefore=$(ssh ${receiver} ". XDPUtils.sh && calculate_packets_drop ${nicName}")
	LogMsg "Before test, Packet drop count on ${receiver} is ${packetDropBefore}"
	# Calculate packets forwarded before tests
	if [ $mode == "xdp" ]; then
		pktForwardBefore=$(ssh ${forwarder} ". XDPUtils.sh && calculate_packets_forward ${nicName}")
	fi
	LogMsg "Before test, Packet forward count on ${forwarder} is ${pktForwardBefore}"

	beforeCPU=$(ssh ${forwarder} 'head -1 /proc/stat')
	LogMsg "CPU Utilization for ${forwarder} is ${beforeCPU}"
	# Start XDPDump on receiver
	start_xdpdump ${receiver} ${nicName}
	# Start XDPDump on forwarder
	if [ $mode == "xdp" ]; then
		start_xdpdump ${forwarder} ${nicName}
	else
		# Start Iptable commands
		ip_forward=$(ssh ${forwarder} "sysctl net.ipv4.ip_forward | cut -d'=' -f 2")
		if [ $ip_forward == 0 ]; then
			LogMsg "Setting ip forward in sysctl"
			ssh ${forwarder} "sysctl -w net.ipv4.ip_forward=1"
		fi
		receiverIP=$((ssh $receiver "/sbin/ifconfig ${nicName} | grep 'inet' | cut -d: -f2") | awk '{print $2}')

		ssh ${forwarder} "iptables -t nat -A PREROUTING -i ${nicName} -p udp -j DNAT --to-destination ${receiverIP}:9999"
		ssh ${forwarder} "iptables -t nat -A POSTROUTING -j MASQUERADE"
		LogMsg "${forwarder} vm setup completed for ip tables"
	fi

	# Start pktgen on Sender
	forwarderSecondMAC=$((ssh ${forwarder} "ip link show ${nicName}") | grep ether | awk '{print $2}')
	LogMsg "Starting dpdk-testpmd on ${sender}"
	core=1
	trx_rx_ips=$(Get_Trx_Rx_Ip_Flags "${forwarder}")
	vfName=$(get_vf_name ${nicName})
	sender_busaddr=$(ethtool -i ${vfName} | grep bus-info | awk '{print $2}')

	sender_testfwd_cmd="$(Create_Timed_Testpmd_Cmd "${test_duration}" "${core}" "${sender_busaddr}" "${nicName}" txonly "failsafe" "${trx_rx_ips}")"
	LogMsg "${sender_testfwd_cmd}"
	testpmd_filename="${LIS_HOME}/dpdk-testfwd-sender-${core}-core-$(date +"%m%d%Y-%H%M%S").log"
	eval "${sender_testfwd_cmd} 2>&1 > ${testpmd_filename} &"
	sleep "${test_duration}"

	killall dpdk-testpmd
	LogMsg "Killing xdpdump on receiver and forwarder"
	ssh ${receiver} "killall xdpdump"
	if [ $mode == "xdp" ];then
		ssh ${forwarder} "killall xdpdump"
	fi

	# Calculate: Sender PPS, Forwarder # packets, receiver # packets
	# Calculate packet drops before tests
	packetDropAfter=$(ssh ${receiver} ". XDPUtils.sh && calculate_packets_drop ${nicName}")
	packetDrop=$(($packetDropAfter - $packetDropBefore))
	LogMsg "After test, Packet recieved count on ${receiver} is ${packetDrop}"
	# Calculate packets forwarded before tests
	if [ $mode == "xdp" ];then
		pktForwardAfter=$(ssh ${forwarder} ". XDPUtils.sh && calculate_packets_forward ${nicName}")
		pktForward=$((pktForwardAfter - pktForwardBefore))
		LogMsg "After test, Packet forward count on ${forwarder} is ${pktForward}"
	fi

	# parse testpmd output to get pps and number of packets
	tx_pps_arr=($(grep Tx-pps: "${testpmd_filename}" | awk '{print $2}'))
	tx_pkts_arr=($(grep TX-packets: "${testpmd_filename}" | awk '{print $2}'))
	packetCount=${tx_pkts_arr[-1]}
	pps=$(( ($(printf '%b + ' "${tx_pps_arr[@]}"\\c)) / ${#tx_pps_arr[@]} ))

	LogMsg "Sender ${mode}: PPS: ${pps} & Packets: ${packetCount}"
	pps_array+=( $pps )
	LogMsg "Forwarder forwarded ${pktForward} packets and Receiver received ${packetDrop} packets"
	packets_received+=( $packetDrop )
	beforeCPUi=$(echo ${beforeCPU} | cut -d' ' -f2)
	afterCPUi=$(echo ${afterCPU} | cut -d' ' -f2)
	cpuUsage=$(( afterCPUi - beforeCPUi ))
	echo "${cores},${mode},${pps},${packetCount},${pktForward},${packetDrop},${cpuUsage}" >> report.csv
	# threshold value check
	fwdLimit=$(( packetCount*packetFwdThreshold/100 ))
	if [ $mode == "xdp" ] && [ $packetDrop -lt $fwdLimit ]; then
		LogErr "receiver did not receive enough packets for ${mode} mode. Receiver received ${packetDrop} which is lower than threshold" \
			"of ${packetFwdThreshold}% of ${packetCount}. Please check logs"
		if [ ${#modes[*]} -eq 1 ]; then
			SetTestStateFailed
			exit 0
		fi
	fi
done
LogMsg "Testcase successfully completed"

if [ ${#pps_array[@]} -eq 2 ]; then
	pps_diff=$((pps_array[0]-pps_array[1]))
	LogMsg "PPS Difference between two modes is ${pps_diff#-}"
	pkts_rec_diff=$((packets_received[0]-packets_received[1]))
	LogMsg "Difference in number of packets received between ${modes[0]} and ${modes[1]} is ${pkts_rec_diff}"
	if [ ${pps_diff#-} -gt 100000 ] || [ ${pkts_rec_diff} -lt 0 ]; then
		LogErr "Forwarding performance of ${modes[0]} is lower than ${modes[1]}"
		SetTestStateFailed
		exit 0
	else
		LogMsg "Forwarding performance of ${modes[0]} is greater than ${modes[1]}"
		SetTestStateCompleted
	fi
else
	LogErr "pps_array does not have required number of entries. Error while running forwarding modes. Please check logs."
	SetTestStateAborted
fi
