#!/bin/bash
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# This script will run DPDk TestPmd test and generate report in .csv file.
# To run this script constants.sh details must.
#
########################################################################################################

HOMEDIR=`pwd`
LOGDIR="${HOMEDIR}/DpdkTestPmdLogs"
CONSTANTS_FILE="./constants.sh"
UTIL_FILE="./utils.sh"
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
# Source constants file and initialize most common variables
UtilsInit

LogMsg "*********INFO: Script execution Started********"
clientIPs=($(ssh root@${client} "hostname -I | awk '{print $1}'"))
if [[ ${clientIPs[1]} == "" ]] || [[ ${clientIPs[2]} == "" ]];
then
	LogMsg "Extra NICs doesn't have ips, do dhclient"
	dhclient eth1 eth2
	ssh root@${server} "dhclient eth1 eth2"
	sleep 5
	clientIPs=($(ssh root@${client} "hostname -I | awk '{print $1}'"))
else
	LogMsg "Extra NICs have ips, collect them for test."
fi
serverIPs=($(ssh root@${server} "hostname -I | awk '{print $1}'"))
echo -e "serverNIC1ip=${serverIPs[1]}\nserverNIC2ip=${serverIPs[2]}\nclientNIC1ip=${clientIPs[1]}\nclientNIC2ip=${clientIPs[2]}" >> ${CONSTANTS_FILE}
. ${CONSTANTS_FILE}
echo "server-vm : eth0 : ${server} : eth1 : ${serverNIC1ip} eth2 : ${serverNIC2ip}"
echo "client-vm : eth0 : ${client} : eth1 : ${clientNIC1ip} eth2 : ${clientNIC2ip}"

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
	SetTestStateRunning
	mv $LOGDIR $LOGDIR-$(date +"%m%d%Y-%H%M%S")
	mkdir -p $LOGDIR
	cores=1
	ssh ${server} "mkdir -p $LOGDIR"
	ssh ${server} "mkdir -p  /mnt/huge; mkdir -p  /mnt/huge-1G; mount -t hugetlbfs nodev /mnt/huge && mount -t hugetlbfs nodev /mnt/huge-1G -o 'pagesize=1G' && echo 4096 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages && echo 1 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages && grep -i hug /proc/meminfo"
	mkdir -p  /mnt/huge; mkdir -p  /mnt/huge-1G; mount -t hugetlbfs nodev /mnt/huge && mount -t hugetlbfs nodev /mnt/huge-1G -o 'pagesize=1G' && echo 4096 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages && echo 1 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages && grep -i hug /proc/meminfo 
	
	for testmode in $modes; do
		LogMsg "Configure huge pages on ${server}"
		LogMsg "TestPmd is starting on ${serverNIC1ip} with ${testmode} mode, duration ${testDuration} secs"
		vdevOption="'net_vdev_netvsc0,iface=$interfaceName,force=1'"
		ssh ${server} "echo 4096 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages && echo 1 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages &&  mount -a && modprobe -a ib_uverbs mlx4_en mlx4_core mlx4_ib;timeout ${testDuration} testpmd -l 1-3 -n 2 -w 0002:00:02.0 --vdev='net_vdev_netvsc0,iface=eth1,force=1' -- --port-topology=chained --nb-cores 1 --forward-mode=${testmode}  --stats-period 1" 2>&1 > $HOMEDIR/dpdkVersion.txt 
		ssh ${server} "pkill testpmd"
		sleep 60
		ssh ${server} "echo 0 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages"
		serverTestPmdCmd="echo 4096 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages && echo 1 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages &&  mount -a && modprobe -a ib_uverbs mlx4_en mlx4_core mlx4_ib;timeout ${testDuration} testpmd -l 0-1 -w 0002:00:02.0 --vdev='net_vdev_netvsc0,iface=eth1,force=1' -- --port-topology=chained --nb-cores 1 --txq 1 --rxq 1 --mbcache=512 --txd=4096 --rxd=4096 --forward-mode=${testmode}  --stats-period 1"
		echo $serverTestPmdCmd
		ssh ${server} $serverTestPmdCmd 2>&1 > $LOGDIR/dpdk-testpmd-${testmode}-receiver-$(date +"%m%d%Y-%H%M%S").log &
		checkCmdExitStatus "TestPmd started on ${serverNIC1ip} with ${testmode} mode, duration ${testDuration} secs"
		LogMsg "Configure huge pages on ${client}"
		
		LogMsg "TestPmd is starting on ${clientNIC1ip} with txonly mode, duration ${testDuration} secs"
		echo "echo 0 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages && echo 0 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages && echo 4096 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages && echo 1 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages &&  modprobe -a ib_uverbs mlx4_en mlx4_core mlx4_ib;timeout ${testDuration} testpmd -l 0-1 -w 0002:00:02.0 --vdev='net_vdev_netvsc0,iface=eth1,force=1' -- --port-topology=chained --nb-cores 1 --txq 1 --rxq 1 --mbcache=512 --txd=4096 --rxd=4096 --forward-mode=txonly  --stats-period 1 2>&1 >> $LOGDIR/dpdk-testpmd-${testmode}-sender.log &"

		echo 4096 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages && echo 1 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages &&  modprobe -a ib_uverbs mlx4_en mlx4_core mlx4_ib;timeout ${testDuration} testpmd -l 0-1 -w 0002:00:02.0 --vdev='net_vdev_netvsc0,iface=eth1,force=1' -- --port-topology=chained --nb-cores 1 --txq 1 --rxq 1 --mbcache=512 --txd=4096 --rxd=4096 --forward-mode=txonly  --stats-period 1 2>&1 > $LOGDIR/dpdk-testpmd-${testmode}-sender-$(date +"%m%d%Y-%H%M%S").log &
		checkCmdExitStatus "TestPmd started on ${clientNIC1ip} with txonly mode, duration ${testDuration} secs"
		sleep ${testDuration}
		LogMsg "reset used huge pages"
		echo 0 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages && echo 0 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages && grep -i hug /proc/meminfo
		ssh ${server} "echo 0 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages && echo 0 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages && grep -i hug /proc/meminfo"
		pkill testpmd
		ssh ${server} "pkill testpmd"
		LogMsg "TestPmd execution for ${testmode} mode is COMPLETED"
	done	
}

testPmdParser ()
{
	LogMsg "*********INFO: Parser Started*********"
	testpmdCsvFile=$HOMEDIR/dpdkTestPmd.csv
	mv $HOMEDIR/dpdkTestPmd.csv $HOMEDIR/dpdkTestPmd-$(date +"%m%d%Y-%H%M%S").csv
	DpdkVersion=`testpmd -v 2>&1 | grep DPDK | tr ":" "\n" | sed 's/^ //g' | sed "s/'//g" | tail -1`
	logFiles=(`ls $LOGDIR/*.log`)
	echo "DpdkVersion,TestMode,Cores,MaxRxPps,TxPps,RxPps,FwdPps,TxBytes,RxBytes,FwdBytes,TxPackets,RxPackets,FwdPackets,TxPacketSize,RxPacketSize" > $testpmdCsvFile
	fileCount=0
	while [ "x${logFiles[$fileCount]}" != "x" ]
	do
		LogMsg "collecting results from ${logFiles[$fileCount]}"
		if [[ ${logFiles[$fileCount]} =~ "rxonly-receiver" ]];
		then
			rxonly_mode="rxonly"
			rxonly_Rxpps_Max=`cat ${logFiles[$fileCount]} | grep Rx-pps: | awk '{print $2}' | sort -n | tail -1`
			rxonly_Rxbytes_Max=`cat ${logFiles[$fileCount]} | grep RX-bytes: | rev | awk '{print $1}' | rev | sort -n | tail -1`
			rxonly_Rxpackets_Max=`cat ${logFiles[$fileCount]} | grep RX-packets: | awk '{print $2}' | sort -n | tail -3| head -1`
			rxonly_RTxpps_Max=`cat ${logFiles[$fileCount]} | grep Tx-pps: | awk '{print $2}' | sort -n | tail -1`
			rxonly_RTxbytes_Max=`cat ${logFiles[$fileCount]} | grep TX-bytes: | rev | awk '{print $1}' | rev | sort -n | tail -1`
			rxonly_RTxpackets_Max=`cat ${logFiles[$fileCount]} | grep TX-packets: | awk '{print $2}' | sort -n | tail -1`
			
			rxonly_Rxpps=(`cat ${logFiles[$fileCount]} | grep Rx-pps: | awk '{print $2}'`)
			rxonly_Rxpps_Avg=$(($(expr $(printf '%b + ' "${rxonly_Rxpps[@]::${#rxonly_Rxpps[@]}}"\\c))/${#rxonly_Rxpps[@]}))
			rxonly_Rxbytes=(`cat ${logFiles[$fileCount]} | grep RX-bytes: | rev | awk '{print $1}' | rev`)
			rxonly_Rxbytes_Avg=$(($(expr $(printf '%b + ' "${rxonly_Rxbytes[@]::${#rxonly_Rxbytes[@]}}"\\c))/${#rxonly_Rxbytes[@]}))
			rxonly_Rxpackets=(`cat ${logFiles[$fileCount]} | grep RX-packets: | awk '{print $2}'`)
			rxonly_Rxpackets_Avg=$(($(expr $(printf '%b + ' "${rxonly_Rxpackets[@]::${#rxonly_Rxpackets[@]}}"\\c))/${#rxonly_Rxpackets[@]}))
			rxonly_RTxpps=(`cat ${logFiles[$fileCount]} | grep Tx-pps: | awk '{print $2}'`)
			rxonly_RTxpps_Avg=$(($(expr $(printf '%b + ' "${rxonly_RTxpps[@]::${#rxonly_RTxpps[@]}}"\\c))/${#rxonly_RTxpps[@]}))
			rxonly_RTxbytes=(`cat ${logFiles[$fileCount]} | grep TX-bytes: | rev | awk '{print $1}' | rev`)
			rxonly_RTxbytes_Avg=$(($(expr $(printf '%b + ' "${rxonly_RTxbytes[@]::${#rxonly_RTxbytes[@]}}"\\c))/${#rxonly_RTxbytes[@]}))
			rxonly_RTxpackets=(`cat ${logFiles[$fileCount]} | grep TX-packets: | awk '{print $2}'`)
			rxonly_RTxpackets_Avg=$(($(expr $(printf '%b + ' "${rxonly_RTxpackets[@]::${#rxonly_RTxpackets[@]}}"\\c))/${#rxonly_RTxpackets[@]}))
		elif [[ ${logFiles[$fileCount]} =~ "rxonly-sender" ]];
		then
			rxonly_mode="rxonly"
			rxonly_Txpps_Max=(`cat ${logFiles[$fileCount]} | grep Tx-pps: | awk '{print $2}' | sort -n | tail -1`)
			rxonly_Txbytes_Max=(`cat ${logFiles[$fileCount]} | grep TX-bytes: | rev | awk '{print $1}' | rev | sort -n | tail -1`)
			rxonly_Txpackets_Max=(`cat ${logFiles[$fileCount]} | grep TX-packets: | awk '{print $2}' | sort -n | tail -1`)
			rxonly_Txpps=(`cat ${logFiles[$fileCount]} | grep Tx-pps: | awk '{print $2}'`)
			rxonly_Txpps_Avg=$(($(expr $(printf '%b + ' "${rxonly_Txpps[@]::${#rxonly_Txpps[@]}}"\\c))/${#rxonly_Txpps[@]}))
			rxonly_Txbytes=(`cat ${logFiles[$fileCount]} | grep TX-bytes: | rev | awk '{print $1}' | rev`)
			rxonly_Txbytes_Avg=$(($(expr $(printf '%b + ' "${rxonly_Txbytes[@]::${#rxonly_Txbytes[@]}}"\\c))/${#rxonly_Txbytes[@]}))
			rxonly_Txpackets=(`cat ${logFiles[$fileCount]} | grep TX-packets: | awk '{print $2}'`)
			rxonly_Txpackets_Avg=$(($(expr $(printf '%b + ' "${rxonly_Txpackets[@]::${#rxonly_Txpackets[@]}}"\\c))/${#rxonly_Txpackets[@]}))
		elif [[ ${logFiles[$fileCount]} =~ "io-receiver" ]];
		then
			io_mode="io"
			io_Rxpps_Max=`cat ${logFiles[$fileCount]} | grep Rx-pps: | awk '{print $2}' | sort -n | tail -1`
			io_Rxbytes_Max=`cat ${logFiles[$fileCount]} | grep RX-bytes: | rev | awk '{print $1}' | rev | sort -n | tail -1`
			io_Rxpackets_Max=`cat ${logFiles[$fileCount]} | grep RX-packets: | awk '{print $2}' | sort -n | tail -3| head -1`
			io_RTxpps_Max=`cat ${logFiles[$fileCount]} | grep Tx-pps: | awk '{print $2}' | sort -n | tail -1`
			io_RTxbytes_Max=`cat ${logFiles[$fileCount]} | grep TX-bytes: | rev | awk '{print $1}' | rev | sort -n | tail -1`
			io_RTxpackets_Max=`cat ${logFiles[$fileCount]} | grep TX-packets: | awk '{print $2}' | sort -n | tail -1`
			
			io_Rxpps=(`cat ${logFiles[$fileCount]} | grep Rx-pps: | awk '{print $2}'`)
			io_Rxpps_Avg=$(($(expr $(printf '%b + ' "${io_Rxpps[@]::${#io_Rxpps[@]}}"\\c))/${#io_Rxpps[@]}))
			io_Rxbytes=(`cat ${logFiles[$fileCount]} | grep RX-bytes: | rev | awk '{print $1}' | rev`)
			io_Rxbytes_Avg=$(($(expr $(printf '%b + ' "${io_Rxbytes[@]::${#io_Rxbytes[@]}}"\\c))/${#io_Rxbytes[@]}))
			io_Rxpackets=(`cat ${logFiles[$fileCount]} | grep RX-packets: | awk '{print $2}'`)
			io_Rxpackets_Avg=$(($(expr $(printf '%b + ' "${io_Rxpackets[@]::${#io_Rxpackets[@]}}"\\c))/${#io_Rxpackets[@]}))
			io_RTxpps=(`cat ${logFiles[$fileCount]} | grep Tx-pps: | awk '{print $2}'`)
			io_RTxpps_Avg=$(($(expr $(printf '%b + ' "${io_RTxpps[@]::${#io_RTxpps[@]}}"\\c))/${#io_RTxpps[@]}))
			io_RTxbytes=(`cat ${logFiles[$fileCount]} | grep TX-bytes: | rev | awk '{print $1}' | rev`)
			io_RTxbytes_Avg=$(($(expr $(printf '%b + ' "${io_RTxbytes[@]::${#io_RTxbytes[@]}}"\\c))/${#io_RTxbytes[@]}))
			io_RTxpackets=(`cat ${logFiles[$fileCount]} | grep TX-packets: | awk '{print $2}'`)
			io_RTxpackets_Avg=$(($(expr $(printf '%b + ' "${io_RTxpackets[@]::${#io_RTxpackets[@]}}"\\c))/${#io_RTxpackets[@]}))
		elif [[ ${logFiles[$fileCount]} =~ "io-sender" ]];
		then
			io_mode="io"
			io_Txpps_Max=(`cat ${logFiles[$fileCount]} | grep Tx-pps: | awk '{print $2}' | sort -n | tail -1`)
			io_Txbytes_Max=(`cat ${logFiles[$fileCount]} | grep TX-bytes: | rev | awk '{print $1}' | rev | sort -n | tail -1`)
			io_Txpackets_Max=(`cat ${logFiles[$fileCount]} | grep TX-packets: | awk '{print $2}' | sort -n | tail -1`)			
			io_Txpps=(`cat ${logFiles[$fileCount]} | grep Tx-pps: | awk '{print $2}'`)
			io_Txpps_Avg=$(($(expr $(printf '%b + ' "${io_Txpps[@]::${#io_Txpps[@]}}"\\c))/${#io_Txpps[@]}))
			io_Txbytes=(`cat ${logFiles[$fileCount]} | grep TX-bytes: | rev | awk '{print $1}' | rev`)
			io_Txbytes_Avg=$(($(expr $(printf '%b + ' "${io_Txbytes[@]::${#io_Txbytes[@]}}"\\c))/${#io_Txbytes[@]}))
			io_Txpackets=(`cat ${logFiles[$fileCount]} | grep TX-packets: | awk '{print $2}'`)
			io_Txpackets_Avg=$(($(expr $(printf '%b + ' "${io_Txpackets[@]::${#io_Txpackets[@]}}"\\c))/${#io_Txpackets[@]}))
		fi
		((fileCount++))
	done
	if [ $rxonly_mode == "rxonly" ];then
		LogMsg "$rxonly_mode pushing to csv file"
		echo $rxonly_Txbytes_Avg $rxonly_Txpackets_Avg
		Tx_Pkt_Size=$((rxonly_Txbytes_Avg/rxonly_Txpackets_Avg))
		Rx_Pkt_Size=$((rxonly_Rxbytes_Avg/rxonly_Rxpackets_Avg))
		echo "$DpdkVersion,$rxonly_mode,$cores,$rxonly_Rxpps_Max,$rxonly_Txpps_Avg,$rxonly_Rxpps_Avg,$rxonly_RTxpps_Avg,$rxonly_Txbytes_Avg,$rxonly_Rxbytes_Avg,$rxonly_RTxbytes_Avg,$rxonly_Txpackets_Avg,$rxonly_Rxpackets_Avg,$rxonly_RTxpackets_Avg,$Tx_Pkt_Size,$Rx_Pkt_Size" >> $testpmdCsvFile
	fi
	if [ $io_mode == "io" ];then
		LogMsg "$io_mode pushing to csv file"	
		Tx_Pkt_Size=$((io_Txbytes_Avg/io_Txpackets_Avg))
		Rx_Pkt_Size=$((io_Rxbytes_Avg/io_Rxpackets_Avg))
		echo "$DpdkVersion,$io_mode,$cores,$io_Rxpps_Max,$io_Txpps_Avg,$io_Rxpps_Avg,$io_RTxpps_Avg,$io_Txbytes_Avg,$io_Rxbytes_Avg,$io_RTxbytes_Avg,$io_Txpackets_Avg,$io_Rxpackets_Avg,$io_RTxpackets_Avg,$Tx_Pkt_Size,$Rx_Pkt_Size" >> $testpmdCsvFile
	fi
}

LogMsg "*********INFO: Starting DPDK Setup execution*********"
./dpdkSetup.sh
checkCmdExitStatus "DPDK Setup"
LogMsg "*********INFO: Starting TestPmd test execution with DPDK ${dpdkVersion}*********"
runTestPmd
checkCmdExitStatus "TestPmd execution"
LogMsg "Collecting testpmd logs from server-vm ${server}"
mv  DpdkTestPmdLogs.tar.gz  DpdkTestPmdLogs-$(date +"%m%d%Y-%H%M%S").tar.gz
tar -cvzf DpdkTestPmdLogs.tar.gz DpdkTestPmdLogs/
LogMsg "*********INFO: Starting TestPmd results parser execution*********"
testPmdParser
checkCmdExitStatus "Parser execution"
LogMsg "*********INFO: TestPmd RESULTS*********"
column -s, -t $testpmdCsvFile
LogMsg "*********INFO: DPDK TestPmd script execution reach END. Completed !!!*********"
SetTestStateCompleted