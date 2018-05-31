#!/bin/bash
#
# This script will run DPDk TestPmd test and generate report in .csv file.
# To run this script constants.sh details must.
#
########################################################################################################

HOMEDIR=`pwd`
LOGDIR="${HOMEDIR}/DpdkTestPmdLogs"
dpdkSrcLink="https://fast.dpdk.org/rel/dpdk-18.02.1.tar.xz"
dpdkSrcTar="${dpdkSrcLink##*/}"
dpdkversion=`echo $dpdkSrc | grep -Po "(\d+\.)+\d+"`
dpdkSrcDir=""
DPDK_BUILD=x86_64-native-linuxapp-gcc
srcIp=""
dstIp=""

CONSTANTS_FILE="./constants.sh"
ICA_TESTCONFIGURATION="TestConfiguration" # The test configuration is running
ICA_TESTRUNNING="TestRunning"           # The test is running
ICA_TESTCOMPLETED="TestCompleted"       # The test completed successfully
ICA_TESTABORTED="TestAborted"           # Error during the setup of the test
ICA_TESTFAILED="TestFailed"             # Error occurred during the test
touch ./dpdkRuntime.log

LogMsg()
{
	echo `date "+%b %d %Y %T"` : "${1}"    # Add the time stamp to the log message
	echo `date "+%b %d %Y %T"` : "${1}" >> $HOMEDIR/dpdkRuntime.log
}

UpdateTestState()
{
    echo "${1}" >> $HOMEDIR/state.txt
}

apt-get -y install ifupdown 
ifup eth1 && ifup eth2
ssh root@server-vm "apt-get -y install ifupdown"
ssh root@server-vm "ifup eth1 && ifup eth2"
sleep 5
serverIPs=($(ssh root@server-vm "hostname -I | awk '{print $1}'"))
clientIPs=($(ssh root@client-vm "hostname -I | awk '{print $1}'"))
rxonly_mode=""
io_mode=""

server=${serverIPs[0]}
serverNIC1ip=${serverIPs[1]}
serverNIC2ip=${serverIPs[2]}
client=${clientIPs[0]}
clientNIC1ip=${clientIPs[1]}
clientNIC2ip=${clientIPs[2]}
echo "server-vm : eth0 : ${server} : eth1 : ${serverNIC1ip} eth2 : ${serverNIC2ip}"
echo "client-vm : eth0 : ${client} : eth1 : ${clientNIC1ip} eth2 : ${clientNIC2ip}"

if [ -e ${CONSTANTS_FILE} ]; then
    source ${CONSTANTS_FILE}
else
    errMsg="Error: missing ${CONSTANTS_FILE} file"
    LogMsg "${errMsg}"
    UpdateTestState $ICA_TESTABORTED
    exit 10
fi

function checkCmdExitStatus ()
{
	exit_status=$?
	cmd=$1

	if [ $exit_status -ne 0 ]; then
		echo "$cmd: FAILED (exit code: $exit_status)" 
		if [ "$2" == "exit" ]
		then
			exit $exit_status
			UpdateTestState ICA_TESTFAILED
		fi 
	else
		echo "$cmd: SUCCESS" 
	fi
}

runTestPmd()
{
	UpdateTestState ICA_TESTRUNNING
	mkdir -p $LOGDIR
	ssh ${server} "mkdir -p $LOGDIR"
	dpdkSrcDir=`ls | grep dpdk-`
	testDuration=60
	
	for testmode in $modes; do
		LogMsg "Configure huge pages on ${server}"
		ssh ${server} "mkdir -p  /mnt/huge; mkdir -p  /mnt/huge-1G; mount -t hugetlbfs nodev /mnt/huge && mount -t hugetlbfs nodev /mnt/huge-1G -o 'pagesize=1G' && echo 4096 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages && echo 1 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages && grep -i hug /proc/meminfo"
		LogMsg "TestPmd is starting on ${serverNIC1ip} with ${testmode} mode, duration ${testDuration} secs"
		vdevOption="'net_vdev_netvsc0,iface=$interfaceName,force=1'"
		serverTestPmdCmd="echo 4096 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages && echo 1 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages &&  mount -a && modprobe -a ib_uverbs mlx4_en mlx4_core mlx4_ib;cd $HOMEDIR/$dpdkSrcDir/x86_64-native-linuxapp-gcc/app && timeout ${testDuration} ./testpmd -l 1-3 -n 2 -w 0002:00:02.0 --vdev='net_vdev_netvsc0,iface=eth1,force=1' -- --port-topology=chained --nb-cores 1 --forward-mode=${testmode}  --stats-period 1"
		echo $serverTestPmdCmd
		ssh ${server} $serverTestPmdCmd  >> $LOGDIR/dpdk-testpmd-${testmode}-receiver.log &
		checkCmdExitStatus "TestPmd started on ${serverNIC1ip} with ${testmode} mode, duration ${testDuration} secs"
		LogMsg "Configure huge pages on ${client}"
		mkdir -p  /mnt/huge; mkdir -p  /mnt/huge-1G; mount -t hugetlbfs nodev /mnt/huge && mount -t hugetlbfs nodev /mnt/huge-1G -o 'pagesize=1G' && echo 4096 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages && echo 1 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages && grep -i hug /proc/meminfo 
		LogMsg "TestPmd is starting on ${clientNIC1ip} with txonly mode, duration ${testDuration} secs"
		echo "echo 0 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages && echo 0 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages && echo 4096 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages && echo 1 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages &&  modprobe -a ib_uverbs mlx4_en mlx4_core mlx4_ib;cd $HOMEDIR/$dpdkSrcDir/x86_64-native-linuxapp-gcc/app && timeout ${testDuration} ./testpmd -l 1-3 -n 2 -w 0002:00:02.0 --vdev='net_vdev_netvsc0,iface=eth1,force=1' -- --port-topology=chained --nb-cores 1 --forward-mode=txonly  --stats-period 1 >> $LOGDIR/dpdk-testpmd-${testmode}-sender.log &"
		
		echo 4096 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages && echo 1 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages &&  modprobe -a ib_uverbs mlx4_en mlx4_core mlx4_ib;cd $HOMEDIR/$dpdkSrcDir/x86_64-native-linuxapp-gcc/app && timeout ${testDuration} ./testpmd -l 1-3 -n 2 -w 0002:00:02.0 --vdev='net_vdev_netvsc0,iface=eth1,force=1' -- --port-topology=chained --nb-cores 1 --forward-mode=txonly  --stats-period 1 >> $LOGDIR/dpdk-testpmd-${testmode}-sender.log &
		checkCmdExitStatus "TestPmd started on ${clientNIC1ip} with txonly mode, duration ${testDuration} secs"
		sleep ${testDuration}
		LogMsg "reset used huge pages"
		echo 0 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages && echo 0 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages && grep -i hug /proc/meminfo
		ssh ${server} "echo 0 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages && echo 0 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages && grep -i hug /proc/meminfo"
	done	
}

testPmdParser ()
{
	LogMsg "*********INFO: Parser Started*********"
	testpmdCsvFile=$HOMEDIR/dpdkTestPmd.csv
	logFiles=(`ls $LOGDIR/*.log`)
	echo ",TestMode,Tx-pps,Rx-pps,Tx-bytes,Rx-bytes,Tx-packets,Rx-packets,RTx-pps,RTx-bytes,RTx-packets,Tx-pkt-size,Rx-pkt-size" > $testpmdCsvFile
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
		echo ",$rxonly_mode,$rxonly_Txpps_Avg,$rxonly_Rxpps_Avg,$rxonly_Txbytes_Avg,$rxonly_Rxbytes_Avg,$rxonly_Txpackets_Avg,$rxonly_Rxpackets_Avg,$rxonly_RTxpps_Avg,$rxonly_RTxbytes_Avg,$rxonly_RTxpackets_Avg,$Tx_Pkt_Size,$Rx_Pkt_Size" >> $testpmdCsvFile
	fi
	if [ $io_mode == "io" ];then
		LogMsg "$io_mode pushing to csv file"	
		Tx_Pkt_Size=$((io_Txbytes_Avg/io_Txpackets_Avg))
		Rx_Pkt_Size=$((io_Rxbytes_Avg/io_Rxpackets_Avg))
		echo ",$io_mode,$io_Txpps_Avg,$io_Rxpps_Avg,$io_Txbytes_Avg,$io_Rxbytes_Avg,$io_Txpackets_Avg,$io_Rxpackets_Avg,$io_RTxpps_Avg,$io_RTxbytes_Avg,$io_RTxpackets_Avg,$Tx_Pkt_Size,$Rx_Pkt_Size" >> $testpmdCsvFile
	fi
}

LogMsg "*********INFO: Starting DPDK Setup execution*********"

./dpdkSetup.sh

LogMsg "*********INFO: Starting TestPmd test execution*********"
runTestPmd
checkCmdExitStatus "TestPmd execution"
LogMsg "Collecting testpmd logs from server-vm ${server}"
tar -cvzf DpdkTestPmdLogs.tar.gz $LOGDIR
LogMsg "*********INFO: Starting TestPmd results parser execution*********"
testPmdParser
checkCmdExitStatus "Parser execution"
LogMsg "*********INFO: DPDK TestPmd script execution reach END. Completed !!!*********"
UpdateTestState ICA_TESTCOMPLETED
