#!/bin/bash
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# This script will run DPDk TestPmd test and generate report in .csv file.
# To run this script constants.sh details must.
#
########################################################################################################

HOMEDIR=$(pwd)
LOGDIR="${HOMEDIR}/DpdkTestPmdLogs"
CONSTANTS_FILE="./constants.sh"
UTIL_FILE="./utils.sh"
DPDK_UTIL_FILE="./dpdkUtils.sh"
rxonly_mode=""
io_mode=""

. ${CONSTANTS_FILE} || {
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

LogMsg "*********INFO: Script execution Started********"
clientIPs=($(ssh root@"${client}" "hostname -I | awk '{print $1}'"))
if [[ ${clientIPs[1]} == "" ]] || [[ ${clientIPs[2]} == "" ]];
then
	LogMsg "Extra NICs doesn't have ips, do dhclient"
	dhclient eth1 eth2
	ssh root@"${server}" "dhclient eth1 eth2"
	sleep 5
	clientIPs=($(ssh root@"${client}" "hostname -I | awk '{print $1}'"))
else
	LogMsg "Extra NICs have ips, collect them for test."
fi
serverIPs=($(ssh root@"${server}" "hostname -I | awk '{print $1}'"))
echo -e "serverNIC1ip=${serverIPs[1]}\nserverNIC2ip=${serverIPs[2]}\nclientNIC1ip=${clientIPs[1]}\nclientNIC2ip=${clientIPs[2]}" >> ${CONSTANTS_FILE}
. ${CONSTANTS_FILE}
echo "server-vm : eth0 : ${server} : eth1 : ${serverNIC1ip} eth2 : ${serverNIC2ip}"
echo "client-vm : eth0 : ${client} : eth1 : ${clientNIC1ip} eth2 : ${clientNIC2ip}"

runTestPmd()
{
	SetTestStateRunning
	mv "$LOGDIR" "$LOGDIR"-$(date +"%m%d%Y-%H%M%S")
	mkdir -p "$LOGDIR"
	cores=1
	ssh "${server}" "mkdir -p $LOGDIR"

	local dpdk_version=$(Get_DPDK_Version "${LIS_HOME}/${DPDK_DIR}")
	local pci_param="-w"
	local dpdk_version_changed="20.11"
	if [[ ! $(printf "${dpdk_version_changed}\n${dpdk_version}" | sort -V | head -n1) == "${dpdk_version}" ]]; then
		pci_param="-a"
	fi

	. ${DPDK_UTIL_FILE} && Hugepage_Setup ${client}
	. ${DPDK_UTIL_FILE} && Hugepage_Setup ${server}
	vf_name_client=$(ssh "${client}" ". utils.sh && get_vf_name 'eth1'")
	pci_info_client=$(ssh "${client}" "ethtool -i $vf_name_client | grep bus-info |  cut -d' ' -f2-")
	LogMsg "pci_info_client $pci_info_client"
	vf_name_server=$(ssh "${server}" ". utils.sh && get_vf_name 'eth1'")
	pci_info_server=$(ssh "${server}" "ethtool -i $vf_name_server | grep bus-info |  cut -d' ' -f2-")
	LogMsg "pci_info_server $pci_info_server"
	trx_rx_ips=$(Get_Trx_Rx_Ip_Flags "${server}")
	if [ ${pmd} = "netvsc" ]; then
		. ${DPDK_UTIL_FILE} && NetvscDevice_Setup "${server}"
		. ${DPDK_UTIL_FILE} && NetvscDevice_Setup "${client}"
		vdev=''
	elif [ ${pmd} = "failsafe" ];then
		vdev="--vdev=net_vdev_netvsc0,iface=eth1,force=1"
	else
		LogWarn "No pmd variable present in the parameters. using failsafe pmd as default one"
		vdev="--vdev=net_vdev_netvsc0,iface=eth1,force=1"
	fi
	# Check testpmd --no-pci if it triggers a kernel crash
	# SIGKILL(9) is required, as the --no-pci makes testpmd hang
	# although SIGINT is sent.
	# TODO: check nic version and then include drivers: mlx4/mlx5.
	modprobe -a ib_uverbs mlx4_en mlx4_core mlx4_ib; \
		timeout --kill-after 10 10 dpdk-testpmd --no-pci -m 1024 -c 0x3 -- -i --total-num-mbufs=16384 --coremask=0x2 --rxq=1 --txq=1

	for testmode in $modes; do
		LogMsg "TestPmd is starting on ${serverNIC1ip} with ${testmode} mode, duration ${testDuration} secs"
		Hugepage_Setup ${server} "set"
		serverTestPmdCmd="modprobe -a ib_uverbs mlx4_en mlx4_core mlx4_ib;timeout ${testDuration} dpdk-testpmd -l 0-1 ${pci_param} $pci_info_server ${vdev} -- --port-topology=chained --nb-cores 1 --txq 1 --rxq 1 --mbcache=512 --txd=4096 --rxd=4096 --forward-mode=${testmode}  --stats-period 1"
		LogMsg "Server Testpmd Command: $serverTestPmdCmd"
		ssh "${server}" "$serverTestPmdCmd" 2>&1 > "$LOGDIR"/dpdk-testpmd-"${testmode}"-receiver-$(date +"%m%d%Y-%H%M%S").log &
		check_exit_status "TestPmd started on ${serverNIC1ip} with ${testmode} mode, duration ${testDuration} secs" "aborted"

		LogMsg "TestPmd is starting on ${clientNIC1ip} with txonly mode, duration ${testDuration} secs"
		LogMsg "timeout ${testDuration} dpdk-testpmd -l 0-1 ${pci_param} $pci_info_client ${vdev} -- --port-topology=chained --nb-cores 1 --txq 1 --rxq 1 --mbcache=512 --txd=4096 --rxd=4096 --forward-mode=txonly --stats-period 1 ${trx_rx_ips} 2>&1 >> $LOGDIR/dpdk-testpmd-${testmode}-sender.log &"

		Hugepage_Setup ${client} "set"
		# Replace modprobe command with Modprobe_setup
		modprobe -a ib_uverbs mlx4_en mlx4_core mlx4_ib
		timeout "${testDuration}" dpdk-testpmd -l 0-1 ${pci_param} ${pci_info_client} ${vdev} -- \
			--port-topology=chained --nb-cores 1 --txq 1 --rxq 1 --mbcache=512 --txd=4096 --rxd=4096 \
			--forward-mode=txonly --stats-period 1 ${trx_rx_ips} 2>&1 > "$LOGDIR"/dpdk-testpmd-"${testmode}"-sender-$(date +"%m%d%Y-%H%M%S").log &
		check_exit_status "TestPmd started on ${clientNIC1ip} with txonly mode, duration ${testDuration} secs" "aborted"
		sleep "${testDuration}"
		pkill dpdk-testpmd
		ssh "${server}" "pkill dpdk-testpmd"

		LogMsg "Reset used huge pages"
		Hugepage_Setup "${client}" "reset"
		Hugepage_Setup "${server}" "reset"

		LogMsg "Wait 60 sec for exiting testpmd"
		sleep 60
		LogMsg "TestPmd execution for ${testmode} mode is COMPLETED"
	done
}

testPmdParser ()
{
	LogMsg "*********INFO: Parser Started*********"
	testpmdCsvFile=$HOMEDIR/dpdkTestPmd.csv
	mv "$HOMEDIR"/dpdkTestPmd.csv "$HOMEDIR"/dpdkTestPmd-$(date +"%m%d%Y-%H%M%S").csv
	DpdkVersion=$(testpmd -v 2>&1 | grep DPDK | tr ":" "\n" | sed 's/^ //g' | sed "s/'//g" | tail -1)
	logFiles=($(ls "$LOGDIR"/*.log))
	echo "DpdkVersion,poll_mode_driver,TestMode,Cores,MaxRxPps,TxPps,RxPps,FwdPps,TxBytes,RxBytes,FwdBytes,TxPackets,RxPackets,FwdPackets,TxPacketSize,RxPacketSize" > "$testpmdCsvFile"
	fileCount=0
	while [ "x${logFiles[$fileCount]}" != "x" ]
	do
		LogMsg "collecting results from ${logFiles[$fileCount]}"
		if [[ ${logFiles[$fileCount]} =~ "rxonly-receiver" ]];
		then
			rxonly_mode="rxonly"
			rxonly_Rxpps_Max=$(cat "${logFiles[$fileCount]}" | grep Rx-pps: | awk '{print $2}' | sort -n | tail -1)
			rxonly_Rxbytes_Max=$(cat "${logFiles[$fileCount]}" | grep RX-bytes: | rev | awk '{print $1}' | rev | sort -n | tail -1)
			rxonly_Rxpackets_Max=$(cat "${logFiles[$fileCount]}" | grep RX-packets: | awk '{print $2}' | sort -n | tail -3| head -1)
			rxonly_RTxpps_Max=$(cat "${logFiles[$fileCount]}" | grep Tx-pps: | awk '{print $2}' | sort -n | tail -1)
			rxonly_RTxbytes_Max=$(cat "${logFiles[$fileCount]}" | grep TX-bytes: | rev | awk '{print $1}' | rev | sort -n | tail -1)
			rxonly_RTxpackets_Max=$(cat "${logFiles[$fileCount]}" | grep TX-packets: | awk '{print $2}' | sort -n | tail -1)

			rxonly_Rxpps=($(cat "${logFiles[$fileCount]}" | grep Rx-pps: | awk '{print $2}'))
			rxonly_Rxpps_Avg=$(($(expr $(printf '%b + ' "${rxonly_Rxpps[@]::${#rxonly_Rxpps[@]}}"\\c))/${#rxonly_Rxpps[@]}))
			rxonly_Rxbytes=($(cat "${logFiles[$fileCount]}" | grep RX-bytes: | rev | awk '{print $1}' | rev))
			rxonly_Rxbytes_Avg=$(($(expr $(printf '%b + ' "${rxonly_Rxbytes[@]::${#rxonly_Rxbytes[@]}}"\\c))/${#rxonly_Rxbytes[@]}))
			rxonly_Rxpackets=($(cat "${logFiles[$fileCount]}" | grep RX-packets: | awk '{print $2}'))
			rxonly_Rxpackets_Avg=$(($(expr $(printf '%b + ' "${rxonly_Rxpackets[@]::${#rxonly_Rxpackets[@]}}"\\c))/${#rxonly_Rxpackets[@]}))
			rxonly_RTxpps=($(cat "${logFiles[$fileCount]}" | grep Tx-pps: | awk '{print $2}'))
			rxonly_RTxpps_Avg=$(($(expr $(printf '%b + ' "${rxonly_RTxpps[@]::${#rxonly_RTxpps[@]}}"\\c))/${#rxonly_RTxpps[@]}))
			rxonly_RTxbytes=($(cat "${logFiles[$fileCount]}" | grep TX-bytes: | rev | awk '{print $1}' | rev))
			rxonly_RTxbytes_Avg=$(($(expr $(printf '%b + ' "${rxonly_RTxbytes[@]::${#rxonly_RTxbytes[@]}}"\\c))/${#rxonly_RTxbytes[@]}))
			rxonly_RTxpackets=($(cat "${logFiles[$fileCount]}" | grep TX-packets: | awk '{print $2}'))
			rxonly_RTxpackets_Avg=$(($(expr $(printf '%b + ' "${rxonly_RTxpackets[@]::${#rxonly_RTxpackets[@]}}"\\c))/${#rxonly_RTxpackets[@]}))
		elif [[ ${logFiles[$fileCount]} =~ "rxonly-sender" ]];
		then
			rxonly_mode="rxonly"
			rxonly_Txpps_Max=($(cat "${logFiles[$fileCount]}" | grep Tx-pps: | awk '{print $2}' | sort -n | tail -1))
			rxonly_Txbytes_Max=($(cat "${logFiles[$fileCount]}" | grep TX-bytes: | rev | awk '{print $1}' | rev | sort -n | tail -1))
			rxonly_Txpackets_Max=($(cat "${logFiles[$fileCount]}" | grep TX-packets: | awk '{print $2}' | sort -n | tail -1))
			rxonly_Txpps=($(cat "${logFiles[$fileCount]}"  | grep Tx-pps: | awk '{print $2}'))
			rxonly_Txpps_Avg=$(($(expr $(printf '%b + ' "${rxonly_Txpps[@]::${#rxonly_Txpps[@]}}"\\c))/${#rxonly_Txpps[@]}))
			rxonly_Txbytes=($(cat "${logFiles[$fileCount]}"  | grep TX-bytes: | rev | awk '{print $1}' | rev))
			rxonly_Txbytes_Avg=$(($(expr $(printf '%b + ' "${rxonly_Txbytes[@]::${#rxonly_Txbytes[@]}}"\\c))/${#rxonly_Txbytes[@]}))
			rxonly_Txpackets=($(cat "${logFiles[$fileCount]}"  | grep TX-packets: | awk '{print $2}'))
			rxonly_Txpackets_Avg=$(($(expr $(printf '%b + ' "${rxonly_Txpackets[@]::${#rxonly_Txpackets[@]}}"\\c))/${#rxonly_Txpackets[@]}))
		elif [[ ${logFiles[$fileCount]} =~ "io-receiver" ]];
		then
			io_mode="io"
			io_Rxpps_Max=$(cat "${logFiles[$fileCount]}"  | grep Rx-pps: | awk '{print $2}' | sort -n | tail -1)
			io_Rxbytes_Max=$(cat "${logFiles[$fileCount]}" | grep RX-bytes: | rev | awk '{print $1}' | rev | sort -n | tail -1)
			io_Rxpackets_Max=$(cat "${logFiles[$fileCount]}" | grep RX-packets: | awk '{print $2}' | sort -n | tail -3| head -1)
			io_RTxpps_Max=$(cat "${logFiles[$fileCount]}" | grep Tx-pps: | awk '{print $2}' | sort -n | tail -1)
			io_RTxbytes_Max=$(cat "${logFiles[$fileCount]}" | grep TX-bytes: | rev | awk '{print $1}' | rev | sort -n | tail -1)
			io_RTxpackets_Max=$(cat "${logFiles[$fileCount]}" | grep TX-packets: | awk '{print $2}' | sort -n | tail -1)

			io_Rxpps=($(cat "${logFiles[$fileCount]}" | grep Rx-pps: | awk '{print $2}'))
			io_Rxpps_Avg=$(($(expr $(printf '%b + ' "${io_Rxpps[@]::${#io_Rxpps[@]}}"\\c))/${#io_Rxpps[@]}))
			io_Rxbytes=($(cat "${logFiles[$fileCount]}" | grep RX-bytes: | rev | awk '{print $1}' | rev))
			io_Rxbytes_Avg=$(($(expr $(printf '%b + ' "${io_Rxbytes[@]::${#io_Rxbytes[@]}}"\\c))/${#io_Rxbytes[@]}))
			io_Rxpackets=($(cat "${logFiles[$fileCount]}" | grep RX-packets: | awk '{print $2}'))
			io_Rxpackets_Avg=$(($(expr $(printf '%b + ' "${io_Rxpackets[@]::${#io_Rxpackets[@]}}"\\c))/${#io_Rxpackets[@]}))
			io_RTxpps=($(cat "${logFiles[$fileCount]}" | grep Tx-pps: | awk '{print $2}'))
			io_RTxpps_Avg=$(($(expr $(printf '%b + ' "${io_RTxpps[@]::${#io_RTxpps[@]}}"\\c))/${#io_RTxpps[@]}))
			io_RTxbytes=($(cat "${logFiles[$fileCount]}" | grep TX-bytes: | rev | awk '{print $1}' | rev))
			io_RTxbytes_Avg=$(($(expr $(printf '%b + ' "${io_RTxbytes[@]::${#io_RTxbytes[@]}}"\\c))/${#io_RTxbytes[@]}))
			io_RTxpackets=($(cat "${logFiles[$fileCount]}" | grep TX-packets: | awk '{print $2}'))
			io_RTxpackets_Avg=$(($(expr $(printf '%b + ' "${io_RTxpackets[@]::${#io_RTxpackets[@]}}"\\c))/${#io_RTxpackets[@]}))
		elif [[ ${logFiles[$fileCount]} =~ "io-sender" ]];
		then
			io_mode="io"
			io_Txpps_Max=($(cat "${logFiles[$fileCount]}" | grep Tx-pps: | awk '{print $2}' | sort -n | tail -1))
			io_Txbytes_Max=($(cat "${logFiles[$fileCount]}" | grep TX-bytes: | rev | awk '{print $1}' | rev | sort -n | tail -1))
			io_Txpackets_Max=($(cat "${logFiles[$fileCount]}" | grep TX-packets: | awk '{print $2}' | sort -n | tail -1))
			io_Txpps=($(cat "${logFiles[$fileCount]}"  | grep Tx-pps: | awk '{print $2}'))
			io_Txpps_Avg=$(($(expr $(printf '%b + ' "${io_Txpps[@]::${#io_Txpps[@]}}"\\c))/${#io_Txpps[@]}))
			io_Txbytes=($(cat "${logFiles[$fileCount]}" | grep TX-bytes: | rev | awk '{print $1}' | rev))
			io_Txbytes_Avg=$(($(expr $(printf '%b + ' "${io_Txbytes[@]::${#io_Txbytes[@]}}"\\c))/${#io_Txbytes[@]}))
			io_Txpackets=($(cat "${logFiles[$fileCount]}"  | grep TX-packets: | awk '{print $2}'))
			io_Txpackets_Avg=$(($(expr $(printf '%b + ' "${io_Txpackets[@]::${#io_Txpackets[@]}}"\\c))/${#io_Txpackets[@]}))
		fi
		((fileCount++))
	done
	# The below echo lines just to avoid the error of SC2034
	if [ "$false" ]; then
		echo "$rxonly_Rxbytes_Max"
		echo "$rxonly_Rxpackets_Max"
		echo "$rxonly_RTxpps_Max"
		echo "$rxonly_RTxbytes_Max"
		echo "$rxonly_RTxpackets_Max"
		echo "$rxonly_Txpps_Max"
		echo "$rxonly_Txbytes_Max"
		echo "$rxonly_Txpackets_Max"
		echo "$io_Rxbytes_Max"
		echo "$io_Rxpackets_Max"
		echo "$io_RTxpps_Max"
		echo "$io_RTxbytes_Max"
		echo "$io_RTxpackets_Max"
		echo "$io_Txpps_Max"
		echo "$io_Txbytes_Max"
		echo "$io_Txpackets_Max"
	fi
	if [ $rxonly_mode == "rxonly" ];then
		LogMsg "$rxonly_mode pushing to csv file"
		echo $rxonly_Txbytes_Avg $rxonly_Txpackets_Avg
		Tx_Pkt_Size=$((rxonly_Txbytes_Avg/rxonly_Txpackets_Avg))
		Rx_Pkt_Size=$((rxonly_Rxbytes_Avg/rxonly_Rxpackets_Avg))
		echo "$DpdkVersion,${pmd},$rxonly_mode,$cores,$rxonly_Rxpps_Max,$rxonly_Txpps_Avg,$rxonly_Rxpps_Avg,$rxonly_RTxpps_Avg,$rxonly_Txbytes_Avg,$rxonly_Rxbytes_Avg,$rxonly_RTxbytes_Avg,$rxonly_Txpackets_Avg,$rxonly_Rxpackets_Avg,$rxonly_RTxpackets_Avg,$Tx_Pkt_Size,$Rx_Pkt_Size" >> "$testpmdCsvFile"
	fi
	if [ $io_mode == "io" ];then
		LogMsg "$io_mode pushing to csv file"
		Tx_Pkt_Size=$((io_Txbytes_Avg/io_Txpackets_Avg))
		Rx_Pkt_Size=$((io_Rxbytes_Avg/io_Rxpackets_Avg))
		echo "$DpdkVersion,${pmd},$io_mode,$cores,$io_Rxpps_Max,$io_Txpps_Avg,$io_Rxpps_Avg,$io_RTxpps_Avg,$io_Txbytes_Avg,$io_Rxbytes_Avg,$io_RTxbytes_Avg,$io_Txpackets_Avg,$io_Rxpackets_Avg,$io_RTxpackets_Avg,$Tx_Pkt_Size,$Rx_Pkt_Size" >> "$testpmdCsvFile"
	fi
}

LogMsg "*********INFO: Starting DPDK Setup execution*********"
DPDK_DIR="dpdk"
LogMsg "Initial DPDK source directory: ${DPDK_DIR}"

./dpdkSetup.sh
check_exit_status "DPDK Setup" "aborted"
LogMsg "*********INFO: Starting TestPmd test execution with DPDK ${dpdkVersion}*********"
runTestPmd
check_exit_status "TestPmd execution" "aborted"
LogMsg "Collecting testpmd logs from server-vm ${server}"
mv  DpdkTestPmdLogs.tar.gz  DpdkTestPmdLogs-$(date +"%m%d%Y-%H%M%S").tar.gz
tar -cvzf DpdkTestPmdLogs.tar.gz DpdkTestPmdLogs/
LogMsg "*********INFO: Starting TestPmd results parser execution*********"
testPmdParser
check_exit_status "Parser execution" "aborted"
LogMsg "*********INFO: TestPmd RESULTS*********"
column -s, -t "$testpmdCsvFile"
LogMsg "*********INFO: DPDK TestPmd script execution reach END. Completed !!!*********"
SetTestStateCompleted