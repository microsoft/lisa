#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#

#############################################################################
#
# Description:
#
# This script contains all dpdk specific functions. The functions here require
# that UtilsInit from utils.sh has been called to set up environment. For ssh
# root login, passwordless login, and without StrictHostChecking are required.
#
#############################################################################

# Below functions intended to aid dpdkSetupAndRunTest

# Requires:
#   - UtilsInit has been called
#   - SSH by root, passwordless login, and no StrictHostChecking. Basically have ran
#     enable_root.sh and enable_passwordless_root.sh from Testscripts/Linux
# Effects:
#    Configures hugepages on machine at IP provided
function Hugepage_Setup() {
	if [ -z "${1}" ]; then
		LogErr "ERROR: must provide target ip to Hugepage_Setup()"
		SetTestStateAborted
		exit 1
	fi

	CheckIP ${1}
	if [ $? -eq 1 ]; then
		LogErr "ERROR: must pass valid ip to Hugepage_Setup()"
		SetTestStateAborted
		exit 1
	fi

	if [ -z "${2}" ]; then
		LogMsg "Huge page setup is running"
		ssh "${1}" "mkdir -p /mnt/huge && mkdir -p /mnt/huge-1G"
		LogMsg "creating huge page directory status: $?"
		ssh "${1}" "mount -t hugetlbfs nodev /mnt/huge && mount -t hugetlbfs nodev /mnt/huge-1G -o 'pagesize=1G'"
		check_exit_status "Huge pages are mounted on ${1}" "exit"
	fi
	if [[ "reset" == "${2}" ]]; then
		ssh "${1}" "echo 0 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages"
		check_exit_status "4KB huge pages are reset on ${1}" "exit"
		ssh "${1}" "echo 0 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages"
		check_exit_status "1GB huge pages are reset on ${1}" "exit"
	else
		ssh "${1}" "echo 4096 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages"
		check_exit_status "4KB huge pages are configured on ${1}" "exit"
		ssh "${1}" "echo 1 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages"
		check_exit_status "1GB huge pages are configured on ${1}" "exit"
	fi
	LogMsg "Huge page setup complete:"
	ssh "${1}" "grep -i huge /proc/meminfo && ls /mnt/"
}

# Requires:
#   - UtilsInit has been called
#   - SSH by root, passwordless login, and no StrictHostChecking. Basically have ran
#     enable_root.sh and enable_passwordless_root.sh from Testscripts/Linux
# Effects:
#    modprobes required modules for dpdk on machine at IP provided
function Modprobe_Setup() {
	if [ -z "${1}" ]; then
		LogErr "ERROR: must provide target ip to Modprobe_Setup()"
		SetTestStateAborted
		exit 1
	fi

	CheckIP ${1}
	if [ $? -eq 1 ]; then
		LogErr "ERROR: must pass valid ip to Modprobe_Setup()"
		SetTestStateAborted
		exit 1
	fi

	local modprobe_cmd="modprobe -a ib_uverbs"
	# known issue on sles15 and ubuntu
	local distro=$(detect_linux_distribution)$(detect_linux_distribution_version)
	if [[ "${distro}" =~ "sles15" || ("${distro}" =~ "ubuntu") ]]; then
		modprobe_cmd="${modprobe_cmd} mlx4_ib mlx5_ib || true"
		LogMsg "Loading mlx4_ib and mlx5_ib modules with ib_uverbs module manually for distro: ${distro}"
	fi

	ssh ${1} "${modprobe_cmd}"
}

# Helper function to Install_Dpdk()
# Requires:
#   - called only from Install_Dpdk()
#   - see Install_Dpdk() requires
#   - arguments: ip, distro
function Install_Dpdk_Dependencies() {
	if [ -z "${1}" -o -z "${2}" ]; then
		LogErr "ERROR: must provide install ip and distro to Install_Dpdk_Dependencies()"
		SetTestStateAborted
		exit 1
	fi

	local install_ip="${1}"
	local distro="${2}"

	CheckIP ${install_ip}
	if [ $? -eq 1 ]; then
		LogErr "ERROR: must pass valid ip to Modprobe_Setup()"
		SetTestStateAborted
		exit 1
	fi

	LogMsg "Detected distro: ${distro}"
	if [[ "${distro}" == ubuntu* ]]; then
		apt_packages="librdmacm-dev librdmacm1 build-essential libnuma-dev libmnl-dev libelf-dev dpkg-dev meson"
		if [[ "${distro}" == "ubuntu16.04" ]]; then
			ssh ${install_ip} ". utils.sh && CheckInstallLockUbuntu && add-apt-repository ppa:canonical-server/dpdk-azure -y"
		else
			apt_packages="${apt_packages} rdma-core"
		fi

		ssh ${install_ip} ". utils.sh && CheckInstallLockUbuntu && update_repos"
		ssh ${install_ip} ". utils.sh && CheckInstallLockUbuntu && apt-get install -y ${apt_packages}"

	elif [[ "${distro}" == rhel7* || "${distro}" == centos7* ]]; then
		ssh ${install_ip} "yum -y --nogpgcheck groupinstall 'Infiniband Support'"
		ssh ${install_ip} "dracut --add-drivers 'mlx4_en mlx4_ib mlx5_ib' -f"
		yum_flags=""
		if [[ "${distro}" == centos7* ]]; then
			# for all releases that are moved into vault.centos.org
			# we have to update the repositories first
			ssh ${install_ip} "yum -y --nogpgcheck install centos-release"
			ssh ${install_ip} "yum clean all"
			ssh ${install_ip} "yum makecache"
			yum_flags="--enablerepo=C*-base --enablerepo=C*-updates"
		fi
		ssh ${install_ip} "yum install --nogpgcheck ${yum_flags} --setopt=skip_missing_names_on_install=False -y gcc make git tar wget dos2unix psmisc kernel-devel-$(uname -r) numactl-devel.x86_64 librdmacm-devel libmnl-devel meson"

	elif [[ "${distro}" =~ sles15* ]]; then
		local kernel=$(uname -r)
		dependencies_install_command="zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install gcc make git tar wget dos2unix psmisc libnuma-devel numactl librdmacm1 rdma-core-devel libmnl-devel meson"
		if [[ "${kernel}" == *azure ]]; then
			ssh "${install_ip}" "zypper install --oldpackage -y kernel-azure-devel=${kernel::-6}"
			dependencies_install_command="${dependencies_install_command} kernel-devel-azure"
		else
			dependencies_install_command="${dependencies_install_command} kernel-default-devel"
		fi

		ssh "${install_ip}" "${dependencies_install_command}"
		ssh "${install_ip}" "ln -sf /usr/include/libmnl/libmnl/libmnl.h /usr/include/libmnl/libmnl.h"
	else
		LogErr "ERROR: unsupported distro ${distro} for DPDK on Azure"
		SetTestStateAborted
		exit 1
	fi
	if [ $? -ne 0 ]; then
		LogErr "ERROR: Failed to install required packages on distro ${distro}"
		SetTestStateFailed
		exit 1
	fi
}

function Install_Dpdk () {
	dpdk_server_ip=${2}
	dpdk_client_ip=${3}
	install_from_ppa=false
	dpdk_version=""

	HOMEDIR=$(pwd)
	export RTE_SDK="${HOMEDIR}/dpdk"
	export RTE_TARGET="x86_64-native-linuxapp-gcc"
	DPDK_DIR="dpdk"
	SetTestStateRunning
	LogMsg "Configuring ${1} ${DISTRO_NAME} ${DISTRO_VERSION} for DPDK test..."
	packages=(gcc make git tar wget dos2unix psmisc make)
	case "${DISTRO_NAME}" in
		oracle|rhel|centos)
			if ! ([ "${DISTRO_NAME}" = "rhel" ] && [[ ${DISTRO_VERSION} == *"8."* ]]) ;then
				ssh "${1}" ". utils.sh && install_epel"
			fi
			ssh "${1}" "yum -y groupinstall 'Infiniband Support' && dracut --add-drivers 'mlx4_en mlx4_ib mlx5_ib' -f && systemctl enable rdma"
			check_exit_status "Install Infiniband Support on ${1}" "exit"
			devel_source=(  "7.5=http://vault.centos.org/7.5.1804/updates/x86_64/Packages/kernel-devel-$(uname -r).rpm"
			                "7.6=http://vault.centos.org/7.6.1810/updates/x86_64/Packages/kernel-devel-$(uname -r).rpm"
			                "8.1=http://vault.centos.org//8.1.1911/BaseOS/x86_64/os/Packages/kernel-devel-$(uname -r).rpm" )
			curr_version=$(ssh "${1}" "grep -E '7.5|7.6|8.1' /etc/redhat-release")
			for source in "${devel_source[@]}" ; do
				KEY="${source%%=*}"
				if [[ "$curr_version" == *"$KEY"* ]]; then
					VALUE="${source##*=}"
					LogMsg "Installing kernel-devel package for $KEY from $VALUE."
					ssh "${1}" "rpm -ivh $VALUE"
				fi
			done
			packages+=(kernel-devel-$(uname -r) numactl-devel.x86_64 librdmacm-devel pkgconfig)
			ssh "${1}" "yum makecache"
			check_package "libmnl-devel"
			if [ $? -eq 0 ]; then
				packages+=("libmnl-devel")
			fi
			check_package "elfutils-libelf-devel"
			if [ $? -eq 0 ]; then
				packages+=("elfutils-libelf-devel")
			fi
			if [[ "${DISTRO_NAME}" = "rhel" ]]; then
				# meson requires ninja-build and python-devel to be installed. [ninja-build ref: https://pkgs.org/download/ninja-build]
				if [[ ${DISTRO_VERSION} == *"8."* ]]; then
					ssh "${1}" ". utils.sh && install_package python3-devel"
					ssh "${1}" "rpm -ivh http://mirror.centos.org/centos/8/PowerTools/x86_64/os/Packages/ninja-build-1.8.2-1.el8.x86_64.rpm"
					ssh "${1}" "rpm -ivh http://mirror.centos.org/centos/8/PowerTools/x86_64/os/Packages/meson-0.49.2-1.el8.noarch.rpm"
				else
					# Required as meson is dependent on python36
					ssh "${1}" ". utils.sh && install_package rh-python36 ninja-build"
					ssh "${1}" 'PATH=$PATH:/opt/rh/rh-python36/root/usr/bin/ && pip install --upgrade pip && pip install meson'
				fi
			else
				if [[ "${DISTRO_NAME}" = "centos" && ${DISTRO_VERSION} == *"8."* ]]; then
					dnf --enablerepo=PowerTools install -y meson
				else
					packages+=(meson)
				fi
			fi
			;;
		ubuntu|debian)
			ssh "${1}" "until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done"
			if [[ "${DISTRO_VERSION}" == "16.04" ]];
			then
				LogMsg "Adding dpdk repo to ${DISTRO_NAME} ${DISTRO_VERSION} for DPDK test..."
				ssh "${1}" ". utils.sh && CheckInstallLockUbuntu && add-apt-repository ppa:canonical-server/dpdk-azure -y"
			else
				packages+=(rdma-core)
			fi
			ssh "${1}" ". utils.sh && CheckInstallLockUbuntu && add-apt-repository 'deb http://cz.archive.ubuntu.com/ubuntu eoan main universe' "
			ssh "${1}" ". utils.sh && CheckInstallLockUbuntu && update_repos"
			packages+=(librdmacm-dev librdmacm1 build-essential libnuma-dev libmnl-dev libelf-dev dpkg-dev meson pkg-config)
			;;
		suse|opensuse|sles)
			ssh "${1}" ". utils.sh && add_sles_network_utilities_repo"
			local kernel=$(uname -r)
			if [[ "${kernel}" == *azure ]];
			then
				ssh "${1}" "zypper install --oldpackage -y kernel-azure-devel=${kernel::-6}"
				packages+=(kernel-devel-azure)
			else
				packages+=(kernel-default-devel)
			fi
			packages+=(libnuma-devel numactl librdmacm1 rdma-core-devel libmnl-devel pkg-config)
			# default meson in SUSE 15-SP1 is 0.46 & required is 0.47. Installing it separately
			ssh "${1}" ". utils.sh && install_package ninja"
			ssh "${1}" "rpm -ivh https://download.opensuse.org/repositories/openSUSE:/Leap:/15.2/standard/noarch/meson-0.54.2-lp152.1.1.noarch.rpm"
			ssh "${1}" "ln -sf /usr/include/libmnl/libmnl/libmnl.h /usr/include/libmnl/libmnl.h"
			;;
		*)
			echo "Unknown distribution"
			SetTestStateAborted
			exit 1
	esac
	ssh "${1}" ". utils.sh && install_package ${packages[@]}"
	ssh "${1}" "if [[ -e '${DPDK_DIR}' ]]; then rm -rf '${DPDK_DIR}'; fi"

	if [[ $dpdkSrcLink =~ .tar ]];
	then
		ssh ${1} "mkdir ${RTE_SDK}"
		dpdkSrcTar="${dpdkSrcLink##*/}"
		dpdk_version=$(echo "$dpdkSrcTar" | grep -Po "(\d+\.)+\d+")
		LogMsg "Installing DPDK from source file $dpdkSrcTar"
		wget_retry "${dpdkSrcLink}" "/tmp" "${1}"
		ssh "${1}" "tar xf /tmp/$dpdkSrcTar -C ${RTE_SDK} --strip-components 1"
		check_exit_status "tar xf /tmp/$dpdkSrcTar on ${1}" "exit"
		LogMsg "dpdk source on ${1} $DPDK_DIR"
	elif [[ $dpdkSrcLink =~ ".git" ]] || [[ $dpdkSrcLink =~ "git:" ]];
	then
		dpdkSrcDir="${dpdkSrcLink##*/}"
		dpdkSrcDir="${dpdkSrcDir%.git/}"
		LogMsg "Installing DPDK from source file $dpdkSrcDir"
		ssh "${1}" git clone "$dpdkSrcLink $DPDK_DIR"
		check_exit_status "git clone $dpdkSrcLink on ${1}" "exit"
		ssh "${1}" "mv ${dpdkSrcDir} ${DPDK_DIR}"
		LogMsg "dpdk source on ${1} $DPDK_DIR"

	elif [[ $dpdkSrcLink =~ "ppa:" ]];
	then
		if [[ $DISTRO_NAME != "ubuntu" && $DISTRO_NAME != "debian" ]];
		then
			echo "PPAs are supported only on Debian based distros."
			SetTestStateAborted
			exit 1
		fi
		ssh "${1}" "add-apt-repository ${dpdkSrcLink} -y -s"
		ssh "${1}" ". utils.sh && update_repos"
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
		ssh "${1}" ". utils.sh && install_package dpdk dpdk-dev"
		check_exit_status "Install DPDK from ppa ${dpdkSrcLink} on ${1}" "exit"
		ssh "${1}" "apt-get source dpdk"
		check_exit_status "Get DPDK sources from ppa on ${1}" "exit"

		dpdk_version=$(ssh "${1}" "dpkg -s 'dpdk' | grep 'Version' | head -1 | awk '{print \$2}' | awk -F- '{print \$1}'")
		dpdk_source="dpdk_${dpdk_version}.orig.tar.xz"
		dpdkSrcDir="dpdk-${dpdk_version}"

		ssh "${1}" "tar xf $dpdk_source"
		ssh "${1}" "mv $dpdkSrcDir dpdk"
		dpdkSrcDir="dpdk"
		check_exit_status "Get DPDK sources from ppa on ${1}" "exit"
	fi

	LogMsg "DPDK source directory: ${DPDK_DIR}"

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
	if type Dpdk_Configure > /dev/null; then
		echo "Calling testcase provided Dpdk_Configure(1) on ${1}"
		if [[ ${DISTRO_NAME} == rhel ]] && ! [[ ${DISTRO_VERSION} == *"8."* ]]; then
			ssh ${1} "cd ${LIS_HOME}/${DPDK_DIR} && PATH=$PATH:/opt/rh/rh-python36/root/usr/bin/ && meson build"
		else
			ssh ${1} "cd ${LIS_HOME}/${DPDK_DIR} && meson build"
		fi
		# shellcheck disable=SC2034
		ssh ${1} ". constants.sh; . utils.sh; . dpdkUtils.sh; cd ${LIS_HOME}/${DPDK_DIR}; $(typeset -f Dpdk_Configure); DPDK_DIR=${DPDK_DIR} LIS_HOME=${LIS_HOME} Dpdk_Configure ${1}"
		ssh ${1} "cd ${LIS_HOME}/${DPDK_DIR}/build && ninja && ninja install && ldconfig"
		check_exit_status "dpdk build on ${1}" "exit"
	else
		if [[ ${DISTRO_NAME} == rhel ]] && ! [[ ${DISTRO_VERSION} == *"8."* ]]; then
			ssh ${1} "cd ${LIS_HOME}/${DPDK_DIR} && PATH=$PATH:/opt/rh/rh-python36/root/usr/bin/ && meson ${RTE_TARGET}"
		else
			ssh ${1} "cd ${LIS_HOME}/${DPDK_DIR} && meson ${RTE_TARGET}"
		fi
		ssh "${1}" "cd $RTE_SDK/$RTE_TARGET && ninja 2>&1 && ninja install 2>&1 && ldconfig"
		check_exit_status "dpdk build on ${1}" "exit"
	fi
	if [[ ${DISTRO_NAME} == rhel || ${DISTRO_NAME} == centos ]]; then
		# For Distros like RHEL, /usr/local not in default paths. Ref: DPDK Installation Documents
		ssh ${1} " echo '/usr/local/lib64' >> /etc/ld.so.conf"
		ssh ${1} " echo '/usr/local/lib' >> /etc/ld.so.conf"
		ssh ${1} "ldconfig"
	fi
	LogMsg "Finished installing dpdk on ${1}"
}

# Below function(s) intended for use by a testcase provided Run_Testcase() function:
#   - Run_Testcase() allows a user to run their own test within a preconfigured DPDK environment
#   - when called, it is gauranteed to have contants.sh, utils.sh, and dpdkUtils.sh sourced
#   - UtilsInit is called in this environment
#   - Run_Testcase() is called on the "sender" VM and should orchestrate the testcase
#     across the other VMs
#   - see other tests for example

# Create_Csv() creates a csv file for use with DPDK-TESTCASE-DRVER and
# outputs that name so the user can write parsed performance data into it
# Requires:
#   - basic environ i.e. have called UtilsInit
# Effects:
#   - creates csv, outputs name, capture to use
function Create_Csv() {
	if [ -z "${LIS_HOME}" ]; then
		LogErr "ERROR: LIS_HOME must be defined in environment"
		SetTestStateAborted
		exit 1
	fi

	local csv_name="${LIS_HOME}/dpdk_test.csv"
	touch ${csv_name}
	echo ${csv_name}
}

# Update_Phase() updates the test "phase"
# The test phase is read by the main testcase loop in DPDK-TESTCASE-DRIVER
# and the testcase provided Alter-Runtime function can read this. This allows
# testcases to control/adjust any aspect of runtime based on the testcase
# running on the VMs. e.g. revoke VF through Azure Infra during DPDK test
# Requires:
#    - basic environ i.e. have called UtilsInit
#    - 1st argument to be message to write to file
# Effects:
#    - Clobbers previous phase with passed phase message
function Update_Phase() {
	if [ -z "${1}" ]; then
		LogErr "ERROR: Must supply phase message to Update_Phase()"
		SetTestStateAborted
		exit 1
	fi

	local msg="${1}"
	LogMsg "Updated phase with: ${msg}"
	echo "${msg}" > ${PHASE_FILE}
}

# Requires:
#    - basic environ i.e. have called UtilsInit
# Effects:
#    - Outputs phase message
function Read_Phase() {
	cat ${PHASE_FILE}
}

# Create_Vm_Synthetic_Vf_Pair_Mappings() matches the name of VM with  its synthetic and
# VF NIC pair.
# Requires:
#   - basic environ i.e. have called UtilsInit
#   - VM_NAMES to be defined as a list of vm names
#   - each vm_name in the list is also a variable that stores its IP
# Effects:
#   - sets global variables of the form:
#       <vm_name>_iface
#       <vm_name>_busaddr
function Create_Vm_Synthetic_Vf_Pair_Mappings() {
	if [ -z "${VM_NAMES}" ]; then
		LogErr "ERROR: VM_NAMES must be defined for Create_Vm_Synthetic_Vf_Pair_Mappings()"
		SetTestStateAborted
		exit 1
	fi

	local name
	for name in $VM_NAMES; do
		# shellcheck disable=SC2034
		local pairs=($(ssh ${!name} "$(typeset -f get_synthetic_vf_pairs); get_synthetic_vf_pairs"))
		if [ "${#pairs[@]}" -eq 0 ]; then
			LogErr "ERROR: No ${name} VFs present"
			SetTestStateFailed
			exit 1
		fi

		# set global if/busaddr pairs
		eval ${name}_iface="${pairs[0]}"
		eval ${name}_busaddr="${pairs[1]}"
	done
}

# Create_Timed_Testpmd_Cmd() creates the testpmd cmd string based on provided args
# Requires:
#   - basic environ i.e. have called UtilsInit
#   - DPDK_DIR is defined in environment
#   - Arguments (in order):
#        1. duration in seconds
#        2. number of cores
#        3. busaddr of VF
#        4. name of corresponding synthetic nic iface
#        5. any of the valid testpmd fwd modes e.g. txonly, mac, rxonly
# Effects:
#   - outputs testpmd command with no redireciton nor ampersand
function Create_Timed_Testpmd_Cmd() {
	if [ -z "${1}" ]; then
		LogErr "ERROR: duration must be passed to Create_Timed_Testpmd_Cmd"
		SetTestStateAborted
		exit 1
	fi
	local duration="${1}"

	cmd="$(Create_Testpmd_Cmd ${2} ${3} ${4} ${5} ${6} ${7})"
	echo "timeout ${duration} ${cmd}"
}

# Create_Testpmd_Cmd() creates the testpmd cmd string based on provided args
# Requires:
#   - basic environ i.e. have called UtilsInit
#   - DPDK_DIR is defined in environment
#   - Arguments (in order):
#        1. number of cores
#        2. busaddr of VF
#        3. name of corresponding synthetic nic iface
#        4. any of the valid testpmd fwd modes e.g. txonly, mac, rxonly
# Effects:
#   - outputs testpmd command with no redireciton nor ampersand

function Create_Testpmd_Cmd() {
	if [ -z "${1}" -o -z "${2}" -o -z "${3}" -o -z "${4}" ]; then
		LogErr "ERROR: cores, busaddr, iface, and testpmd mode must be passed to Create_Testpmd_Cmd"
		SetTestStateAborted
		exit 1
	fi

	if [ -z "${LIS_HOME}" -o -z "${DPDK_DIR}" ]; then
		LogErr "ERROR: DPDK_DIR and LIS_HOME must be defined before calling Create_Testpmd_Cmd()"
		SetTestStateAborted
		exit 1
	fi

	local core="${1}"
	local busaddr="${2}"
	local iface="${3}"
	local mode="${4}"
	local pmd="${5}"
	local additional_params="${6}"

	local dpdk_version=$(Get_DPDK_Version "${LIS_HOME}/${DPDK_DIR}")
	local pci_param="-w ${busaddr}"
	local dpdk_version_changed="20.11"
	if [[ ! $(printf "${dpdk_version_changed}\n${dpdk_version}" | sort -V | head -n1) == "${dpdk_version}" ]]; then
		pci_param="-a ${busaddr}"
	fi
	# partial strings to concat
	local testpmd="dpdk-testpmd"
	local eal_opts=""
	local eal_debug_opts="--log-level=eal,debug --log-level=mlx,debug"
	case "$pmd" in
		netvsc)
			DEV_UUID=$(basename $(readlink /sys/class/net/eth1/device))
			NET_UUID="f8615163-df3e-46c5-913f-f2d2f965ed0e"
			modprobe uio_hv_generic
			echo $NET_UUID > /sys/bus/vmbus/drivers/uio_hv_generic/new_id &>/dev/null
			echo $DEV_UUID > /sys/bus/vmbus/drivers/hv_netvsc/unbind &>/dev/null
			echo $DEV_UUID > /sys/bus/vmbus/drivers/uio_hv_generic/bind &>/dev/null
			eal_opts="-l 0-${core} ${pci_param} ${eal_debug_opts} --log-level=netvsc,debug --"
			;;
		failsafe)
			eal_opts="-l 0-${core} ${pci_param} --vdev='net_vdev_netvsc0,iface=${iface}' ${eal_debug_opts} --log-level=failsafe,debug --"
			;;
		*)
			LogMsg "Not supported PMD $pmd. Abort."
			SetTestStateAborted
			exit 0
			;;
	esac

	local testpmd_opts0="--port-topology=chained --nb-cores ${core} --txq ${core} --rxq ${core}"
	local testpmd_opts1="--mbcache=512 --txd=4096 --rxd=4096 --forward-mode=${mode} --stats-period 1 --tx-offloads=0x800e ${additional_params}"

	echo "${testpmd} ${eal_opts} ${testpmd_opts0} ${testpmd_opts1}"
}

# Below function(s) intended for use by a testcase provided Dpdk_Configure() function:
#   - Dpdk_Configure() lets a testcase configure dpdk before compilation
#   - when called, it is gauranteed to have contants.sh, utils.sh, and dpdkUtils.sh
#     sourced; it will be called on the target machine in dpdk top level dir,
#     and it will be passed target machine's ip
#   - UtilsInit is not called in this environment

# Requires:
#   - called only from dpdk top level directory
#   - type [SRC | DST] and testpmd ip to configure as arguments
# Modifies:
#   - local testpmd tx src and destination ips
function Testpmd_Ip_Setup() {
	if [ -z "${1}" -o -z "${2}" ]; then
		LogErr "ERROR: must provide ip type as SRC or DST and testpmd ip to Testpmd_Ip_Setup()"
		SetTestStateAborted
		exit 1
	fi

	local ip_type=${1}
	if [ "${ip_type}" != "SRC" -a "${ip_type}" != "DST" ]; then
		LogErr "ERROR: ip type invalid use SRC or DST Testpmd_Ip_Setup()"
		SetTestStateAborted
		exit 1
	fi

	local ip_for_testpmd=${2}

	local ip_arr=($(echo ${ip_for_testpmd} | sed "s/\./ /g"))
	local ip_addr="define IP_${ip_type}_ADDR ((${ip_arr[0]}U << 24) | (${ip_arr[1]} << 16) | (${ip_arr[2]} << 8) | ${ip_arr[3]})"
	local ip_config_cmd="sed -i 's/define IP_${ip_type}_ADDR.*/${ip_addr}/' app/test-pmd/txonly.c"
	LogMsg "${ip_config_cmd}"
	eval "${ip_config_cmd}"
}

# Requires:
#   - called only from dpdk top level directory
# Modifies:
#   - local testpmd txonly to support multiple flows
function Testpmd_Multiple_Tx_Flows_Setup() {
	local num_port_code="#define NUM_SRC_PORTS 8"
	local port_arr_code="static uint16_t src_ports[NUM_SRC_PORTS] = {200,300,400,500,600,700,800,900};"
	local port_code="pkt_udp_hdr.src_port = rte_cpu_to_be_16(src_ports[nb_pkt % NUM_SRC_PORTS]);"

	sed -i "54i ${num_port_code}" app/test-pmd/txonly.c
	sed -i "55i ${port_arr_code}" app/test-pmd/txonly.c

	# We need to add port_code line after the nb_pkt is defined
	lookup_line_nb_packet='for (nb_pkt = 0; nb_pkt < nb_pkt_per_burst; nb_pkt++) {'
	local lines_to_be_replaced=$(grep -nir "${lookup_line_nb_packet}" app/test-pmd/txonly.c| awk '{print $1}' | tr -d ':''')
	local line_index=1
	for line in $lines_to_be_replaced
	do
		line_to_be_replaced=$(($line_index + $line))
		sed -i "${line_to_be_replaced}i ${port_code}" app/test-pmd/txonly.c
		line_index=$(($line_index + 1))
	done

	# Fallback to previous implementation
	if [[ -z "${lines_to_be_replaced}" ]]; then
		sed -i "234i ${port_arr_code}" app/test-pmd/txonly.c
	fi
}

# Requires:
#   - called only from dpdk top level directory
#   - first argument to is destination IP
#   - requires ip forwarding to be turned on in the VM
# Modifies:
#   - local testpmd mac mode to forward packets to supplied ip
# Notes:
#   - Be aware of subnets
function Testpmd_Macfwd_To_Dest() {
	local dpdk_version=$(Get_DPDK_Version "${LIS_HOME}/${DPDK_DIR}")
	local dpdk_version_changed_mac_fwd="19.08"
	local dpdk_version_changed_mac_fwd2="20.11"

	local ptr_code="struct ipv4_hdr *ipv4_hdr;"
	local offload_code="ol_flags |= PKT_TX_IP_CKSUM; ol_flags |= PKT_TX_IPV4;"
	local dst_addr=$(echo ${1} | sed 'y/\./,/')
	local dst_addr_code="ipv4_hdr = rte_pktmbuf_mtod_offset(mb, struct ipv4_hdr *, sizeof(struct ether_hdr)); ipv4_hdr->dst_addr = rte_be_to_cpu_32(IPv4(${dst_addr}));"

	LogMsg "DPDK version: ${dpdk_version}. DPDK version changed: ${dpdk_version_changed_mac_fwd}"
	if [[ ! $(printf "${dpdk_version_changed_mac_fwd}\n${dpdk_version}" | sort -V | head -n1) == "${dpdk_version}" ]]; then
		LogMsg "Using newer forwarding code insertion"
		ptr_code="struct rte_ipv4_hdr *rte_ipv4_hdr1;"
		dst_addr_code="rte_ipv4_hdr1 = rte_pktmbuf_mtod_offset(mb, struct rte_ipv4_hdr *, sizeof(struct rte_ether_hdr)); rte_ipv4_hdr1->dst_addr = rte_be_to_cpu_32(RTE_IPV4(${dst_addr}));"
	else
		LogMsg "Using legacy forwarding code insertion"
	fi

	# TODO: Replace line number updates with actual code
	sed -i "53i ${ptr_code}" app/test-pmd/macfwd.c
	if [[ ! $(printf "${dpdk_version_changed_mac_fwd2}\n${dpdk_version}" | sort -V | head -n1) == "${dpdk_version}" ]]; then
		sed -i "82i ${offload_code}" app/test-pmd/macfwd.c
		sed -i "93i ${dst_addr_code}" app/test-pmd/macfwd.c
	else
		sed -i "90i ${offload_code}" app/test-pmd/macfwd.c
		sed -i "101i ${dst_addr_code}" app/test-pmd/macfwd.c
	fi
}

function Get_DPDK_Version() {
	version_file_path="${1}/VERSION"
	meson_config_path="${1}/meson.build"
	dpdk_version=""
	if [ -f "${version_file_path}" ]; then
		dpdk_version=$(cat "${version_file_path}")
	elif [ -f "${meson_config_path}" ]; then
		dpdk_version=$(grep -m 1 "version:" $meson_config_path | awk '{print $2}' | tr -d "\`'\,")
	fi
	echo $dpdk_version
}

function Get_Trx_Rx_Ip_Flags() {
	receiver="${1}"
	local dpdk_version=$(Get_DPDK_Version "${LIS_HOME}/${DPDK_DIR}")
	local dpdk_version_changed_tx_ips="19.05"
	trx_rx_ips=""
	if [[ ! $(printf "${dpdk_version_changed_tx_ips}\n${dpdk_version}" | sort -V | head -n1) == "${dpdk_version}" ]]; then
		local dpdk_ips_cmd="hostname -I"
		local sender_dpdk_ips=($(eval "${dpdk_ips_cmd}"))
		local receiver_dpdk_ips=($(ssh "${receiver}" "${dpdk_ips_cmd}"))
		trx_rx_ips="--tx-ip=${sender_dpdk_ips[1]},${receiver_dpdk_ips[1]}"
	fi
	echo "${trx_rx_ips}"
}

function wget_retry() {
	url=$1
	dest=$2
	remote_ip=$3

	max_retries=3
	retry_timeout=3
	log_msg="Downloading ${url} on ${remote_ip} to ${dest}."
	err_log_msg="Could not download ${url} on ${remote_ip}."

	while [ $max_retries -gt 0 ]; do
		LogMsg "${log_msg}"
		ssh_output=$(ssh "${remote_ip}" "wget --tries 3 --retry-connrefused '${url}' -P ${dest}")
		if [ $? = 0 ]; then
			LogMsg "Successully downloading"
			break
		else
			LogErr "${ssh_output}"
			LogErr "${err_log_msg}. Retrying..."
			max_retries=$(($max_retries-1))
			sleep $retry_timeout
		fi
	done
	if [ $max_retries -eq 0 ]; then
		LogMsg "${err_log_msg}"
		SetTestStateAborted
		exit 1
	fi
}

function NetvscDevice_Setup() {
	if [ -z "${1}" ]; then
		LogErr "ERROR: must provide target ip to NetvscDevice_Setup()"
		SetTestStateAborted
		exit 1
	fi

	CheckIP ${1}
	if [ $? -eq 1 ]; then
		LogErr "ERROR: must pass valid ip to NetvscDevice_Setup()"
		SetTestStateAborted
		exit 1
	fi
	NET_UUID="f8615163-df3e-46c5-913f-f2d2f965ed0e"
	DEV_UUID_pre=$(ssh "${1}" "readlink /sys/class/net/eth1/device")
	DEV_UUID=$(basename ${DEV_UUID_pre})
	ssh "${1}" "modprobe uio_hv_generic"
	ssh "${1}" "echo ${NET_UUID} > /sys/bus/vmbus/drivers/uio_hv_generic/new_id"
	ssh "${1}" "echo ${DEV_UUID} > /sys/bus/vmbus/drivers/hv_netvsc/unbind"
	ssh "${1}" "echo ${DEV_UUID} > /sys/bus/vmbus/drivers/uio_hv_generic/bind"
}