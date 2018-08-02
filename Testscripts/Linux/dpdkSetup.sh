#!/bin/bash
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# This script will do setup huge pages and DPDK installation with SRC & DST IPs for DPDk TestPmd test.
# To run this script constants.sh details must.
#
########################################################################################################

HOMEDIR=`pwd`
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
    echo "${1}" > $HOMEDIR/state.txt
}

LogMsg "*********INFO: Script execution Started********"

if [ -e ${CONSTANTS_FILE} ]; then
    source ${CONSTANTS_FILE}
else
    errMsg="Error: missing ${CONSTANTS_FILE} file"
    LogMsg "${errMsg}"
    UpdateTestState $ICA_TESTABORTED
    exit 10
fi

dpdkSrcTar="${dpdkSrcLink##*/}"
dpdkVersion=`echo $dpdkSrcTar | grep -Po "(\d+\.)+\d+"`
dpdkSrcDir=""
DPDK_BUILD=x86_64-native-linuxapp-gcc
srcIp=""
dstIp=""

dhclient eth1 eth2
ssh root@${server} "dhclient eth1 eth2"
sleep 5
clientIPs=($(ssh root@${client} "hostname -I | awk '{print $1}'"))
serverIPs=($(ssh root@${server} "hostname -I | awk '{print $1}'"))

serverNIC1ip=${serverIPs[1]}
serverNIC2ip=${serverIPs[2]}

clientNIC1ip=${clientIPs[1]}
clientNIC2ip=${clientIPs[2]}

echo "server-vm : eth0 : ${server} : eth1 : ${serverNIC1ip} eth2 : ${serverNIC2ip}"
echo "client-vm : eth0 : ${client} : eth1 : ${clientNIC1ip} eth2 : ${clientNIC2ip}"

function checkCmdExitStatus ()
{
	exit_status=$?
	cmd=$1

	if [ $exit_status -ne 0 ]; then
		echo "$cmd: FAILED (exit code: $exit_status)"
		UpdateTestState ICA_TESTFAILED
		exit $exit_status
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
	ssh ${1} "grep -i hug /proc/meminfo"
	ssh ${1} "echo 4096 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages"
	ssh ${1} "echo 1 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages"
	ssh ${1} "grep -i hug /proc/meminfo"	
}

function installDPDK ()
{
	UpdateTestState ICA_TESTCONFIGURATION
	DISTRO=`grep -ihs "buntu\|Suse\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux\|clear-linux-os" /etc/{issue,*release,*version} /usr/lib/os-release`
	srcIp=${2}
	dstIp=${3}
	LogMsg "Configuring ${1} for DPDK test..."
	if [[ $DISTRO =~ "Ubuntu" ]];
	then
		LogMsg "Detected UBUNTU"
		ssh ${1} "until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done"
		ssh ${1} "add-apt-repository ppa:canonical-server/dpdk-mlx-tech-preview"
		ssh ${1} "apt-get update"
		LogMsg "Configuring ${1} for DPDK test..."
		ssh ${1} "apt-get install -y gcc wget psmisc tar make dpdk dpdk-doc dpdk-dev libdpdk-dev librdmacm-dev librdmacm1 build-essential libnuma-dev libpcap-dev ibverbs-utils"
	elif [[ $DISTRO =~ "CentOS Linux release 7" ]] || [[ $DISTRO =~ "Red Hat Enterprise Linux Server release 7" ]]; 
	then
		LogMsg "Detected RHEL/CENTOS 7.x"
		ssh ${1} "yum -y groupinstall 'Infiniband Support'"
		ssh ${1} "yum install -y kernel-devel-`uname -r` gcc make psmisc numactl-devel.x86_64 numactl-debuginfo.x86_64 numad.x86_64 numactl.x86_64 numactl-libs.x86_64 libpcap-devel librdmacm-devel librdmacm dpdk-doc dpdk-devel librdmacm-utils libibcm libibverbs-utils libibverbs"
		ssh ${1} "dracut --add-drivers 'mlx4_en mlx4_ib mlx5_ib' -f "
		ssh ${1} "systemctl enable rdma"
	elif [[ $DISTRO =~ "SUSE Linux Enterprise Server 15" ]];
	then
		LogMsg "Detected SLES 15"
		ssh ${1} "zypper addrepo https://download.opensuse.org/repositories/network:utilities/SLE_15/network:utilities.repo"
		ssh ${1} "zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys refresh"
		ssh ${1} "zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install kernel-devel kernel-default-devel wget tar bc gcc make psmisc libnuma-devel numactl numad libpcap-devel librdmacm1 librdmacm-utils rdma-core-devel libdpdk-17_11-0"
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
	LogMsg "Starting DPDK build make on ${1}"
	ssh ${1} "cd $HOMEDIR/$dpdkSrcDir/$DPDK_BUILD && make -j8"
	checkCmdExitStatus "dpdk build on ${1}"
	LogMsg "*********INFO: Installed DPDK version on ${1} is ${dpdkVersion} ********"
}

# Script start from here
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
