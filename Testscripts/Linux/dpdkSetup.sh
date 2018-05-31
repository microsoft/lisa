#!/bin/bash
#
# This script will do setup huge pages and DPDK installation with SRC & DST IPs for DPDk TestPmd test.
# To run this script constants.sh details must.
#
########################################################################################################

HOMEDIR=`pwd`
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
		fi 
	else
		echo "$cmd: SUCCESS" 
	fi
}

function hugePageSetup ()
{
	UpdateTestState "Huge page setup is running"
	ssh ${1} "mkdir -p  /mnt/huge"
	ssh ${1} "mkdir -p  /mnt/huge-1G"
	ssh ${1} "mount -t hugetlbfs nodev /mnt/huge"
	ssh ${1} "mount -t hugetlbfs nodev /mnt/huge-1G -o 'pagesize=1G'" 
	ssh ${1} "mount -l | grep mnt"
	ssh ${1} "grep 'Hugepagesize' /proc/meminfo"
	ssh ${1} "echo 4096 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages"
	ssh ${1} "echo 1 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages"
	ssh ${1} "grep 'Hugepagesize' /proc/meminfo"	
}

function installDPDK ()
{
	UpdateTestState ICA_TESTCONFIGURATION
	DISTRO=`grep -ihs "buntu\|Suse\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux\|clear-linux-os" /etc/{issue,*release,*version} /usr/lib/os-release`
	srcIp=${2}
	dstIp=${3}
	
	if [[ $DISTRO =~ "Ubuntu 18.04" ]];
	then
		LogMsg "Detected UBUNTU"
		LogMsg "Configuring ${1} for DPDK test..."
		srcIp=${2}
		dstIp=${3}
		ssh ${1} "until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done"
		ssh ${1} "add-apt-repository ppa:canonical-server/dpdk-mlx-tech-preview"
		ssh ${1} "apt-get update"
		LogMsg "Configuring ${1} for DPDK test..."
		ssh ${1} "apt-get install -y gcc wget tar make dpdk-doc dpdk-dev libdpdk-dev librdmacm-dev librdmacm1 build-essential libnuma-dev libpcap-dev ibverbs-utils"
	elif [[ $DISTRO =~ "Ubuntu 16.04" ]];
	then
		LogMsg "Detected UBUNTU 16.04"
		LogMsg "Configuring ${1} for DPDK test..."
		ssh ${1} "wget  http://content.mellanox.com/ofed/MLNX_OFED-4.3-1.0.1.0/MLNX_OFED_LINUX-4.3-1.0.1.0-ubuntu16.04-x86_64.tgz"
		ssh ${1} "tar xvf MLNX_OFED_LINUX-4.3-1.0.1.0-ubuntu16.04-x86_64.tgz"
		ssh ${1} "cd MLNX_OFED_LINUX-4.3-1.0.1.0-ubuntu16.04-x86_64 && ./mlnxofedinstall --upstream-libs --guest --dpdk --force"
		checkCmdExitStatus "MLX driver install on ${1}"
		srcIp=${2}
		dstIp=${3}
		ssh ${1} "until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done"
		ssh ${1} "add-apt-repository ppa:canonical-server/dpdk-mlx-tech-preview"
		ssh ${1} "apt-get update"
		LogMsg "Configuring ${1} for DPDK test..."
		ssh ${1} "apt-get install -y gcc wget tar make dpdk-doc dpdk-dev libdpdk-dev librdmacm-dev librdmacm1 build-essential libnuma-dev libpcap-dev ibverbs-utils"
	elif [[ $DISTRO =~ "CentOS Linux release 7" ]] || [[ $DISTRO =~ "Red Hat Enterprise Linux Server release 7" ]]; then
		LogMsg "Detected RHEL/CENTOS 7.x"
		ssh ${1} "yum -y groupinstall 'Infiniband Support'"
		ssh ${1} "yum install -y kernel-devel-`uname -r` gcc make numactl-devel.x86_64 numactl-debuginfo.x86_64 numad.x86_64 numactl.x86_64 numactl-libs.x86_64 libpcap-devel librdmacm-devel librdmacm dpdk-doc dpdk-devel librdmacm-utils libibcm libibverbs-utils libibverbs"
		ssh ${1} "dracut --add-drivers 'mlx4_en mlx4_ib mlx5_ib' -f "
		ssh ${1} "systemctl enable rdma"
		
		dpdkSrcLink="https://dpdk.org/browse/dpdk/snapshot/dpdk-18.05-rc2.tar.gz"
		dpdkSrcTar="${dpdkSrcLink##*/}"
		dpdkversion=`echo $dpdkSrc | grep -Po "(\d+\.)+\d+"`
	else
		LogMsg "Unknown Distro"
		UpdateTestState "TestAborted"
		UpdateSummary "Unknown Distro, test aborted"
		return 1
	fi
	LogMsg "Installing DPDK from source file $dpdkSrcTar"
	ssh ${1} "wget $dpdkSrcLink -P /tmp"
	ssh ${1} "tar xvf /tmp/$dpdkSrcTar"
	dpdkSrcDir=`ls | grep dpdk-`
	LogMsg "dpdk source on ${1} $dpdkSrcDir"
	if [ ! -z "$srcIp" -a "$srcIp" != " " ];
	then
		LogMsg "dpdk build with NIC SRC IP $srcIp ADDR on ${1}"
		srcIpArry=( `echo $srcIp | sed "s/\./ /g"` )
		srcIpAddrs="define IP_SRC_ADDR ((${srcIpArry[0]}U << 24) | (${srcIpArry[1]} << 16) | ( ${srcIpArry[2]} << 8) | ${srcIpArry[3]})"
		srcIpConfigCmd="sed -i 's/define IP_SRC_ADDR.*/$srcIpAddrs/' $HOMEDIR/$dpdkSrcDir/app/test-pmd/txonly.c"
		LogMsg "ssh ${1} $srcIpConfigCmd"
		ssh ${1} $srcIpConfigCmd
		checkCmdExitStatus "SRC IP configuration on ${1}"
	else
		LogMsg "dpdk build with default DST IP ADDR on ${1}"
	fi
	if [ ! -z "$dstIp" -a "$dstIp" != " " ];
	then
		LogMsg "dpdk build with NIC DST IP $dstIp ADDR on ${1}"
		dstIpArry=( `echo $dstIp | sed "s/\./ /g"` )
		dstIpAddrs="define IP_DST_ADDR ((${dstIpArry[0]}U << 24) | (${dstIpArry[1]} << 16) | (${dstIpArry[2]} << 8) | ${dstIpArry[3]})"
		dstIpConfigCmd="sed -i 's/define IP_DST_ADDR.*/$dstIpAddrs/' $HOMEDIR/$dpdkSrcDir/app/test-pmd/txonly.c"
		LogMsg "ssh ${1} $dstIpConfigCmd"
		ssh ${1} $dstIpConfigCmd
		checkCmdExitStatus "DST IP configuration on ${1}"
	else
		LogMsg "dpdk build with default DST IP ADDR on ${1}"
	fi	
	LogMsg "MLX_PMD flag enabling on ${1}"
	ssh ${1} "sed -i 's/^CONFIG_RTE_LIBRTE_MLX4_PMD=n/CONFIG_RTE_LIBRTE_MLX4_PMD=y/g' $HOMEDIR/$dpdkSrcDir/config/common_base"
	checkCmdExitStatus "${1} CONFIG_RTE_LIBRTE_MLX4_PMD=y"
	ssh ${1} "cd $HOMEDIR/$dpdkSrcDir && make config O=$DPDK_BUILD T=$DPDK_BUILD"
	ssh ${1} "cd $HOMEDIR/$dpdkSrcDir/$DPDK_BUILD && make -j8"
	checkCmdExitStatus "dpdk build on ${1}"
}

# Script start from here
LogMsg "*********INFO: Script execution Started********"
LogMsg "*********INFO: Starting Huge page configuration*********"
LogMsg "INFO: Configuring huge pages on client ${client}..."
hugePageSetup ${client}

LogMsg "INFO: Configuring huge pages on server ${server}..."
hugePageSetup ${server}

LogMsg "*********INFO: Starting setup & configuration of DPDK*********"
LogMsg "INFO: Installing DPDK on client ${client}..."
installDPDK ${client} ${clientNIC1ip} ${serverNIC1ip}

LogMsg "INFO: Installing DPDK on server ${server}..."
installDPDK ${server} ${serverNIC1ip} ${clientNIC1ip}

LogMsg "*********INFO: DPDK setup script execution reach END. Completed !!!*********"
