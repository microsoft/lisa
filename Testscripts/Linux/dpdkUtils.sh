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
#     enableRoot.sh and enablePasswordLessRoot.sh from Testscripts/Linux
# Effects:
#    Configures hugepages on machine at IP provided
function hugepage_setup() {
	if [ -z "${1}" ]; then
		LogErr "ERROR: must provide target ip to hugepage_setup()"
		SetTestStateAborted
		exit 1
	fi

	CheckIP ${1}
	if [ $? -eq 1 ]; then
		LogErr "ERROR: must pass valid ip to hugepage_setup()"
		SetTestStateAborted
		exit 1
	fi

	local hugepage_cmd="mkdir -p /mnt/huge; mount -t hugetlbfs nodev /mnt/huge && \
		echo 4096 | tee /sys/devices/system/node/node*/hugepages/hugepages-2048kB/nr_hugepages > /dev/null"

	ssh ${1} "${hugepage_cmd}"
}

# Requires:
#   - UtilsInit has been called
#   - SSH by root, passwordless login, and no StrictHostChecking. Basically have ran
#     enableRoot.sh and enablePasswordLessRoot.sh from Testscripts/Linux
# Effects:
#    modprobes required modules for dpdk on machine at IP provided
function modprobe_setup() {
	if [ -z "${1}" ]; then
		LogErr "ERROR: must provide target ip to modprobe_setup()"
		SetTestStateAborted
		exit 1
	fi

	CheckIP ${1}
	if [ $? -eq 1 ]; then
		LogErr "ERROR: must pass valid ip to modprobe_setup()"
		SetTestStateAborted
		exit 1
	fi

	local modprobe_cmd="modprobe -a ib_uverbs"
	# known issue on sles15
	local distro=$(detect_linux_distribution)$(detect_linux_distribution_version)
	if [[ "${distro}" == "sles15" ]]; then
		modprobe_cmd="${modprobe_cmd} mlx4_ib mlx5_ib"
	fi

	ssh ${1} "${modprobe_cmd}"
}

# Helper function to install_dpdk()
# Requires:
#   - called only from install_dpdk()
#   - see install_dpdk() requires
#   - arguments: ip, distro
function install_dpdk_dependencies() {
	if [ -z "${1}" -o -z "${2}" ]; then
		LogErr "ERROR: must provide install ip and distro to install_dpdk_dependencies()"
		SetTestStateAborted
		exit 1
	fi

	local install_ip="${1}"
	local distro="${2}"

	CheckIP ${install_ip}
	if [ $? -eq 1 ]; then
		LogErr "ERROR: must pass valid ip to modprobe_setup()"
		SetTestStateAborted
		exit 1
	fi

	if [[ "${distro}" == ubuntu* ]]; then
		if [[ "${distro}" == "ubuntu16.04" ]]; then
			LogMsg "Detected ubuntu16.04"
			ssh ${install_ip} "add-apt-repository ppa:canonical-server/dpdk-azure -y"
		elif [[ "${distro}" == "ubuntu18.04" ]]; then
			LogMsg "Detected ubuntu18.04"
		else
			LogErr "ERROR: unsupported ubuntu version for dpdk on Azure"
			SetTestStateAborted
			exit 1
		fi

		ssh ${install_ip} "apt-get update"
		ssh ${install_ip} "apt-get install -y librdmacm-dev librdmacm1 build-essential libnuma-dev libmnl-dev"

	elif [[ "${distro}" == "rhel7.5" || "${distro}" == centos7.5* ]]; then
		LogMsg "Detected (rhel/centos)7.5"

		ssh ${install_ip} "yum -y groupinstall 'Infiniband Support'"
		ssh ${install_ip} "dracut --add-drivers 'mlx4_en mlx4_ib mlx5_ib' -f"
		ssh ${install_ip} "yum install -y gcc make git tar wget dos2unix psmisc kernel-devel-$(uname -r) numactl-devel.x86_64 librdmacm-devel libmnl-devel"

	elif [[ "${distro}" == "sles15" ]]; then
		LogMsg "Detected sles15"

		local kernel=$(uname -r)
		if [[ "${kernel}" == *azure ]]; then
			ssh ${install_ip} "zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install gcc make git tar wget dos2unix psmisc kernel-azure kernel-devel-azure libnuma-devel numactl librdmacm1 rdma-core-devel libmnl-devel"
		else
			ssh ${install_ip} "zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install gcc make git tar wget dos2unix psmisc kernel-default-devel libnuma-devel numactl librdmacm1 rdma-core-devel libmnl-devel"
		fi

		ssh ${install_ip} "ln -s /usr/include/libmnl/libmnl/libmnl.h /usr/include/libmnl/libmnl.h"
	else
		LogErr "ERROR: unsupported distro for dpdk on Azure"
		SetTestStateAborted
		exit 1
	fi
}

# Requires:
#   - basic environ i.e. have called UtilsInit
#   - ${1} dpdk install target ip
#   - SSH by root, passwordless login, and no StrictHostChecking. Basically have ran
#     enableRoot.sh and enablePasswordLessRoot.sh from Testscripts/Linux
# Modifies:
#   - vm at ip ${1} to install dpdk with src ip ${2} to dst ip ${3} if provided
# Effects:
#   - does NOT set up hugepages or modprobe (see other funcs)
#	- only installs dpdk on first IP provided
#   - now sets DPDK_DIR global
function install_dpdk() {
	if [ -z "${LIS_HOME}" ]; then
		LogErr "ERROR: LIS_HOME must be defined before calling install_dpdk()"
		SetTestStateAborted
		exit 1
	fi

	if [ -z "${1}" ]; then
		LogErr "ERROR: Must supply ip of host to install_dpdk()"
		SetTestStateAborted
		exit 1
	fi

	CheckIP ${1}
	if [ $? -eq 1 ]; then
		LogErr "ERROR: must pass valid ip to install_dpdk()"
		SetTestStateAborted
		exit 1
	fi
	local install_ip=${1}
	LogMsg "Installing dpdk on ${install_ip}"

	# when available update to dpdk latest
	if [ -z "${DPDK_LINK}" ]; then
		DPDK_LINK="https://fast.dpdk.org/rel/dpdk-18.08.tar.xz"
		LogMsg "DPDK_LINK missing from environment; using ${DPDK_LINK}"
	fi

	local distro=$(detect_linux_distribution)$(detect_linux_distribution_version)
	install_dpdk_dependencies $install_ip $distro

	# set DPDK_DIR global
	if [[ $DPDK_LINK =~ .tar ]]; then
		DPDK_DIR="dpdk-$(echo ${DPDK_LINK} | grep -Po "(\d+\.)+\d+")"
		ssh ${install_ip} "mkdir $DPDK_DIR"
		ssh ${install_ip} "wget -O - ${DPDK_LINK} | tar -xJ -C ${DPDK_DIR} --strip-components=1"
	elif [[ $DPDK_LINK =~ ".git" ]] || [[ $DPDK_LINK =~ "git:" ]]; then
		DPDK_DIR="${DPDK_LINK##*/}"
		ssh ${install_ip} "git clone ${DPDK_LINK} ${DPDK_DIR}"
	fi
	LogMsg "dpdk source on ${install_ip} at ${DPDK_DIR}"

	LogMsg "MLX_PMD flag enabling on ${install_ip}"
	ssh ${install_ip} "cd ${LIS_HOME}/${DPDK_DIR} && make config T=x86_64-native-linuxapp-gcc"
	ssh ${install_ip} "sed -ri 's,(MLX._PMD=)n,\1y,' ${LIS_HOME}/${DPDK_DIR}/build/.config"

	if type dpdk_configure > /dev/null; then
		echo "Calling testcase provided dpdk_configure(install_ip) on ${install_ip}"
		ssh ${install_ip} ". constants.sh; . utils.sh; . dpdkUtils.sh; cd ${LIS_HOME}/${DPDK_DIR}; $(typeset -f dpdk_configure); dpdk_configure ${install_ip}"
	fi

	ssh ${install_ip} "cd ${LIS_HOME}/${DPDK_DIR} && make -j"
	ssh ${install_ip} "cd ${LIS_HOME}/${DPDK_DIR} && make install"

	LogMsg "Finished installing dpdk on ${install_ip}"
}

# Below function(s) intended for use by a testcase provided dpdk_configure() function:
#   - dpdk_configure() lets a testcase configure dpdk before compilation
#   - when called, it is gauranteed to have contants.sh, utils, and dpdkUtils.sh
#     sourced; it will be called on the target machine in dpdk top level dir,
#     and it will be passed target machine's ip
#   - UtilsInit is not called in this environment

# Requires:
#   - called only from dpdk top level directory
#   - type [SRC | DST] and testpmd ip to configure as arguments
#   - configures this machine's testpmd tx src and destination ips
function testpmd_ip_setup() {
	if [ -z "${1}" -o -z "${2}" ]; then
		LogErr "ERROR: must provide ip type as SRC or DST and testpmd ip to testpmd_ip_setup()"
		SetTestStateAborted
		exit 1
	fi

	local ip_type=${1}
	if [ "${ip_type}" != "SRC" -a "${ip_type}" != "DST" ]; then
		LogErr "ERROR: ip type invalid use SRC or DST testpmd_ip_setup()"
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