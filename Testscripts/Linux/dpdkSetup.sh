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
UTIL_FILE="./utils.sh"
DPDK_BUILD=x86_64-native-linuxapp-gcc
srcIp=""
dstIp=""

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

function hugePageSetup ()
{
	LogMsg "Huge page setup is running"
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
	SetTestStateRunning
	srcIp=${2}
	dstIp=${3}
	LogMsg "Configuring ${1} ${DISTRO_NAME} ${DISTRO_VERSION} for DPDK test..."
	packages=(gcc make git tar wget dos2unix psmisc make)
	case "${DISTRO_NAME}" in
		oracle|rhel|centos)
			ssh ${1} ". ${UTIL_FILE} && install_epel"
			ssh ${1} "yum -y groupinstall 'Infiniband Support' && dracut --add-drivers 'mlx4_en mlx4_ib mlx5_ib' -f && systemctl enable rdma"
			checkCmdExitStatus "Install Infiniband Support on ${1}"
			packages+=(kernel-devel-`uname -r` numactl-devel.x86_64 librdmacm-devel) 
			;;
		ubuntu|debian)
			ssh ${1} "until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done"
			if [[ "${DISTRO_VERSION}" == "16.04" ]] || [[ "${DISTRO_VERSION}" == "14.04" ]];
			then
				LogMsg "Adding dpdk repo to ${DISTRO_NAME} ${DISTRO_VERSION} for DPDK test..."
				ssh ${1} "add-apt-repository ppa:canonical-server/dpdk-azure -y"
			fi
			ssh ${1} ". ${UTIL_FILE} && update_repos"
			packages+=(librdmacm-dev librdmacm1 build-essential libnuma-dev libelf-dev)
			;;
		suse|opensuse|sles)
			ssh ${1} ". ${UTIL_FILE} && add_sles_network_utilities_repo"
			local kernel=$(uname -r)
			if [[ "${kernel}" == *azure ]];
			then
				packages+=(kernel-devel-azure)
			else
				packages+=(kernel-default-devel)
			fi
			packages+=(libnuma-devel numactl librdmacm1 rdma-core-devel libmnl-devel)
			;;
		*)
			echo "Unknown distribution"
			SetTestStateAborted
			exit 1
	esac
	ssh ${1} ". ${UTIL_FILE} && install_package ${packages[@]}"

	if [[ $dpdkSrcLink =~ .tar ]];
	then
		dpdkSrcTar="${dpdkSrcLink##*/}"
		dpdkVersion=`echo $dpdkSrcTar | grep -Po "(\d+\.)+\d+"`
		LogMsg "Installing DPDK from source file $dpdkSrcTar"
		ssh ${1} "wget $dpdkSrcLink -P /tmp"
		ssh ${1} "tar xvf /tmp/$dpdkSrcTar"
		checkCmdExitStatus "tar xvf /tmp/$dpdkSrcTar on ${1}"
		dpdkSrcDir="${dpdkSrcTar%%".tar"*}"
		LogMsg "dpdk source on ${1} $dpdkSrcDir"
	elif [[ $dpdkSrcLink =~ ".git" ]] || [[ $dpdkSrcLink =~ "git:" ]];
	then
		dpdkSrcDir="${dpdkSrcLink##*/}"
		LogMsg "Installing DPDK from source file $dpdkSrcDir"
		ssh ${1} git clone $dpdkSrcLink
		checkCmdExitStatus "git clone $dpdkSrcLink on ${1}"
		cd $dpdkSrcDir
		LogMsg "dpdk source on ${1} $dpdkSrcDir"
	else
		LogMsg "Provide proper link $dpdkSrcLink"
	fi

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
	ssh ${1} "cd $HOMEDIR/$dpdkSrcDir/$DPDK_BUILD && make -j8 && make install"
	checkCmdExitStatus "dpdk build on ${1}"
	LogMsg "*********INFO: Installed DPDK version on ${1} is ${dpdkVersion} ********"
}

# Script start from here
LogMsg "*********INFO: Starting Huge page configuration*********"
LogMsg "INFO: Configuring huge pages on client ${client}..."
hugePageSetup ${client}

LogMsg "*********INFO: Starting setup & configuration of DPDK*********"
LogMsg "INFO: Installing DPDK on client ${client}..."
installDPDK ${client} ${clientNIC1ip} ${serverNIC1ip}

if [[ ${client} == ${server} ]];
then
	LogMsg "Skip DPDK setup on server"
	SetTestStateCompleted
else
	LogMsg "INFO: Configuring huge pages on server ${server}..."
	hugePageSetup ${server}
	LogMsg "INFO: Installing DPDK on server ${server}..."
	installDPDK ${server} ${serverNIC1ip} ${clientNIC1ip}
fi
LogMsg "*********INFO: DPDK setup script execution reach END. Completed !!!*********"
