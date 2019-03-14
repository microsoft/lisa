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
	ssh "${1}" "echo 1 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages"
	check_exit_status "1GB huge pages are configured on ${1}" "exit"
}

function install_dpdk () {
	dpdk_server_ip=${2}
	dpdk_client_ip=${3}
	install_from_ppa=false
	dpdk_version=""

	SetTestStateRunning
	LogMsg "Configuring ${1} ${DISTRO_NAME} ${DISTRO_VERSION} for DPDK test..."
	packages=(gcc make git tar wget dos2unix psmisc make)
	case "${DISTRO_NAME}" in
		oracle|rhel|centos)
			ssh "${1}" ". ${UTIL_FILE} && install_epel"
			ssh "${1}" "yum -y groupinstall 'Infiniband Support' && dracut --add-drivers 'mlx4_en mlx4_ib mlx5_ib' -f && systemctl enable rdma"
			check_exit_status "Install Infiniband Support on ${1}" "exit"
			ssh "${1}" "grep 7.5 /etc/redhat-release && curl https://partnerpipelineshare.blob.core.windows.net/kernel-devel-rpms/CentOS-Vault.repo > /etc/yum.repos.d/CentOS-Vault.repo"
			packages+=(kernel-devel-$(uname -r) numactl-devel.x86_64 librdmacm-devel) 
			;;
		ubuntu|debian)
			ssh "${1}" "until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done"
			if [[ "${DISTRO_VERSION}" == "16.04" ]];
			then
				LogMsg "Adding dpdk repo to ${DISTRO_NAME} ${DISTRO_VERSION} for DPDK test..."
				ssh "${1}" "add-apt-repository ppa:canonical-server/dpdk-azure -y"
			fi
			ssh "${1}" ". ${UTIL_FILE} && update_repos"
			packages+=(librdmacm-dev librdmacm1 build-essential libnuma-dev libelf-dev rdma-core)
			;;
		suse|opensuse|sles)
			ssh "${1}" ". ${UTIL_FILE} && add_sles_network_utilities_repo"
			local kernel=$(uname -r)
			if [[ "${kernel}" == *azure ]];
			then
				ssh "${1}" "zypper install --oldpackage -y kernel-azure-devel=${kernel::-6}"
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
	ssh "${1}" ". ${UTIL_FILE} && install_package ${packages[@]}"

	if [[ $dpdkSrcLink =~ .tar ]];
	then
		dpdkSrcTar="${dpdkSrcLink##*/}"
		dpdk_version=$(echo "$dpdkSrcTar" | grep -Po "(\d+\.)+\d+")
		LogMsg "Installing DPDK from source file $dpdkSrcTar"
		ssh "${1}" "wget $dpdkSrcLink -P /tmp"
		ssh "${1}" "tar xf /tmp/$dpdkSrcTar"
		check_exit_status "tar xf /tmp/$dpdkSrcTar on ${1}" "exit"
		dpdkSrcDir="${dpdkSrcTar%%".tar"*}"
		LogMsg "dpdk source on ${1} $dpdkSrcDir"
	elif [[ $dpdkSrcLink =~ ".git" ]] || [[ $dpdkSrcLink =~ "git:" ]];
	then
		dpdkSrcDir="${dpdkSrcLink##*/}"
		dpdkSrcDir="${dpdkSrcDir%.git/}"
		LogMsg "Installing DPDK from source file $dpdkSrcDir"
		ssh "${1}" git clone "$dpdkSrcLink"
		check_exit_status "git clone $dpdkSrcLink on ${1}" "exit"
		LogMsg "dpdk source on ${1} $dpdkSrcDir"
	elif [[ $dpdkSrcLink =~ "ppa:" ]];
	then
		if [[ $DISTRO_NAME != "ubuntu" && $DISTRO_NAME != "debian" ]];
		then
			echo "PPAs are supported only on Debian based distros."
			SetTestStateAborted
			exit 1
		fi
		ssh "${1}" "add-apt-repository ${dpdkSrcLink} -y -s"
		ssh "${1}" ". ${UTIL_FILE} && update_repos"
		install_from_ppa=true
	elif [[ $dpdkSrcLink =~ "native" || $dpdkSrcLink == "" ]];
	then
		if [[ $DISTRO_NAME != "ubuntu" && $DISTRO_NAME != "debian" ]];
		then
			echo "Native installs are supported only on Debian based distros."
			SetTestStateAborted
			exit 1
		fi
		ssh "${1}" "sed -i '/deb-src/s/^# //' /etc/apt/sources.list"
		check_exit_status "Enable source repos on ${1}" "exit"
		install_from_ppa=true
	else
		LogMsg "DPDK source link not supported: '${dpdkSrcLink}'"
		SetTestStateAborted
		exit 1
	fi

	if [[ $install_from_ppa == true ]];
	then
		ssh "${1}" ". ${UTIL_FILE} && install_package dpdk dpdk-dev"
		check_exit_status "Install DPDK from ppa ${dpdkSrcLink} on ${1}" "exit"
		ssh "${1}" "apt-get source dpdk"
		check_exit_status "Get DPDK sources from ppa on ${1}" "exit"

		dpdk_version=$(ssh "${1}" "dpkg -s 'dpdk' | grep 'Version' | head -1 | awk '{print \$2}' | awk -F- '{print \$1}'")
		dpdk_source="dpdk_${dpdk_version}.orig.tar.xz"
		dpdkSrcDir="dpdk-${dpdk_version}"

		ssh "${1}" "tar xf $dpdk_source"
		check_exit_status "Get DPDK sources from ppa on ${1}" "exit"
	fi

	ssh "${1}" "mv ${dpdkSrcDir} ${RTE_SDK}"

	if [ ! -z "$dpdk_server_ip" -a "$dpdk_server_ip" != " " ];
	then
		LogMsg "dpdk build with NIC SRC IP $dpdk_server_ip ADDR on ${1}"
		srcIpArry=( $(echo "$dpdk_server_ip" | sed "s/\./ /g") )
		srcIpAddrs="define IP_SRC_ADDR ((${srcIpArry[0]}U << 24) | (${srcIpArry[1]} << 16) | ( ${srcIpArry[2]} << 8) | ${srcIpArry[3]})"
		srcIpConfigCmd="sed -i 's/define IP_SRC_ADDR.*/$srcIpAddrs/' $RTE_SDK/app/test-pmd/txonly.c"
		LogMsg "ssh ${1} $srcIpConfigCmd"
		ssh "${1}" "$srcIpConfigCmd"
		check_exit_status "SRC IP configuration on ${1}" "exit"
	else
		LogMsg "dpdk build with default DST IP ADDR on ${1}"
	fi
	if [ ! -z "$dpdk_client_ip" -a "$dpdk_client_ip" != " " ];
	then
		LogMsg "dpdk build with NIC DST IP $dpdk_client_ip ADDR on ${1}"
		dstIpArry=( $(echo "$dpdk_client_ip" | sed "s/\./ /g") )
		dstIpAddrs="define IP_DST_ADDR ((${dstIpArry[0]}U << 24) | (${dstIpArry[1]} << 16) | (${dstIpArry[2]} << 8) | ${dstIpArry[3]})"
		dstIpConfigCmd="sed -i 's/define IP_DST_ADDR.*/$dstIpAddrs/' $RTE_SDK/app/test-pmd/txonly.c"
		LogMsg "ssh ${1} $dstIpConfigCmd"
		ssh "${1}" "$dstIpConfigCmd"
		check_exit_status "DST IP configuration on ${1}" "exit"
	else
		LogMsg "dpdk build with default DST IP ADDR on ${1}"
	fi

	LogMsg "MLX_PMD flag enabling on ${1}"
	ssh "${1}" "sed -i 's/^CONFIG_RTE_LIBRTE_MLX4_PMD=n/CONFIG_RTE_LIBRTE_MLX4_PMD=y/g' $RTE_SDK/config/common_base"
	check_exit_status "${1} CONFIG_RTE_LIBRTE_MLX4_PMD=y" "exit"
	ssh "${1}" "cd $RTE_SDK && make config O=$RTE_TARGET T=$RTE_TARGET"
	LogMsg "Starting DPDK build make on ${1}"
	ssh "${1}" "cd $RTE_SDK/$RTE_TARGET && make -j8 && make install"
	check_exit_status "dpdk build on ${1}" "exit"

	LogMsg "*********INFO: Installed DPDK version on ${1} is ${dpdkVersion} ********"
}


# Script start from here

LogMsg "*********INFO: Script execution Started********"
echo "server-vm : eth0 : ${server} : eth1 : ${serverNIC1ip} eth2 : ${serverNIC2ip}"
echo "client-vm : eth0 : ${client} : eth1 : ${clientNIC1ip} eth2 : ${clientNIC2ip}"

LogMsg "*********INFO: Starting Huge page configuration*********"
LogMsg "INFO: Configuring huge pages on client ${client}..."
setup_huge_pages "${client}"

LogMsg "*********INFO: Starting setup & configuration of DPDK*********"
LogMsg "INFO: Installing DPDK on client ${client}..."
install_dpdk "${client}" "${clientNIC1ip}" "${serverNIC1ip}"

if [[ ${client} == ${server} ]];
then
	LogMsg "Skip DPDK setup on server"
else
	LogMsg "INFO: Configuring huge pages on server ${server}..."
	setup_huge_pages "${server}"
	LogMsg "INFO: Installing DPDK on server ${server}..."
	install_dpdk "${server}" "${serverNIC1ip}" "${clientNIC1ip}"
fi

SetTestStateCompleted
LogMsg "*********INFO: DPDK setup completed*********"
