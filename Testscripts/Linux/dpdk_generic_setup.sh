#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# This script will do setup huge pages
# and DPDK installation on client and server machines.

HOMEDIR=$(pwd)
export RTE_SDK="${HOMEDIR}/dpdk"
export RTE_TARGET="x86_64-native-linuxapp-gcc"
UTIL_FILE="./utils.sh"

# Source utils.sh
. utils.sh || {
	echo "ERROR: unable to source utils.sh!"
	echo "TestAborted" > state.txt
	exit 0
}

# Source constants file and initialize most common variables
UtilsInit

function setup_huge_pages () {
	LogMsg "Huge page setup is running"
	ssh "${1}" "mkdir -p /mnt/huge && mkdir -p /mnt/huge-1G"
	ssh "${1}" "mount -t hugetlbfs nodev /mnt/huge && mount -t hugetlbfs nodev /mnt/huge-1G -o 'pagesize=1G'"
	check_exit_status "Huge pages are mounted on ${1}" "exit"
	ssh "${1}" "echo 4096 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages"
	check_exit_status "4KB huge pages are configured on ${1}" "exit"
	ssh "${1}" "echo 8 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages"
	check_exit_status "1GB huge pages are configured on ${1}" "exit"
}

function install_dpdk () {
	SetTestStateRunning
	LogMsg "Configuring ${1} ${DISTRO_NAME} ${DISTRO_VERSION} for DPDK test..."
	packages=(gcc make git tar wget dos2unix psmisc make)
	case "${DISTRO_NAME}" in
		ubuntu|debian)
			ssh "${1}" "until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done"
			if [[ "${DISTRO_VERSION}" == "16.04" ]];
			then
				LogMsg "Adding dpdk repo to ${DISTRO_NAME} ${DISTRO_VERSION} for DPDK test..."
				ssh "${1}" "add-apt-repository ppa:canonical-server/dpdk-azure -y"
			fi
			ssh "${1}" ". ${UTIL_FILE} && update_repos"
			packages+=(build-essential libnuma-dev libmnl-dev libibverbs-dev autoconf libtool)
			;;
		*)
			echo "Unknown distribution"
			SetTestStateAborted
			exit 1
	esac
	ssh "${1}" ". ${UTIL_FILE} && install_package ${packages[@]}"

	if [[ $dpdkSrcLink =~ .tar ]];
	then
		dpdkSrcTar="${dpdkSrcLink##*/}"
		dpdkVersion=$(echo "$dpdkSrcTar" | grep -Po "(\d+\.)+\d+")
		LogMsg "Installing DPDK from source file $dpdkSrcTar"
		ssh "${1}" "wget $dpdkSrcLink -P /tmp"
		ssh "${1}" "tar xf /tmp/$dpdkSrcTar"
		check_exit_status "tar xf /tmp/$dpdkSrcTar on ${1}" "exit"
		dpdkSrcDir="${dpdkSrcTar%%".tar"*}"
		LogMsg "dpdk source on ${1} $dpdkSrcDir"
	elif [[ $dpdkSrcLink =~ ".git" ]] || [[ $dpdkSrcLink =~ "git:" ]];
	then
		dpdkSrcDir="${dpdkSrcLink##*/}"
		LogMsg "Installing DPDK from source file $dpdkSrcDir"
		ssh "${1}" git clone "$dpdkSrcLink"
		check_exit_status "git clone $dpdkSrcLink on ${1}" "exit"
		LogMsg "dpdk source on ${1} $dpdkSrcDir"
	else
		LogMsg "Provide proper link $dpdkSrcLink"
	fi

	ssh "${1}" "mv ${dpdkSrcDir} ${RTE_SDK}"

	LogMsg "MLX_PMD flag enabling on ${1}"
	ssh "${1}" "sed -ri 's,(MLX._PMD=)n,\1y,' ${RTE_SDK}/config/common_base"
	check_exit_status "sed -ri 's,(MLX._PMD=)n,\1y,' ${RTE_SDK}/config/common_base" "exit"
	ssh "${1}" "cd ${RTE_SDK} && make config O=${RTE_TARGET} T=${RTE_TARGET}"
	LogMsg "Starting DPDK build make on ${1}"
	ssh "${1}" "cd ${RTE_SDK}/${RTE_TARGET} && make -j16 && make install"
	check_exit_status "dpdk build on ${1}" "exit"
	LogMsg "*********INFO: Installed DPDK version on ${1} is ${dpdkVersion} ********"
}


# Script start from here

LogMsg "*********INFO: Script execution Started********"
echo "server-vm : eth0 : ${server}"
echo "client-vm : eth0 : ${client}"

LogMsg "*********INFO: Starting Huge page configuration*********"
LogMsg "INFO: Configuring huge pages on client ${client}..."
setup_huge_pages "${client}"

LogMsg "*********INFO: Starting setup & configuration of DPDK*********"
LogMsg "INFO: Installing DPDK on client ${client}..."
install_dpdk "${client}"

if [[ ${client} == ${server} ]];
then
	LogMsg "Skip DPDK setup on server"
	SetTestStateCompleted
else
	LogMsg "INFO: Configuring huge pages on server ${server}..."
	setup_huge_pages "${server}"
	LogMsg "INFO: Installing DPDK on server ${server}..."
	install_dpdk "${server}"
	SetTestStateCompleted
fi
LogMsg "*********INFO: DPDK setup completed*********"
