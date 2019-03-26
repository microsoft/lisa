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
	# known issue on sles15
	local distro=$(detect_linux_distribution)$(detect_linux_distribution_version)
	if [[ "${distro}" == "sles15" ]]; then
		modprobe_cmd="${modprobe_cmd} mlx4_ib mlx5_ib"
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
		ssh ${install_ip} "apt-get install -y librdmacm-dev librdmacm1 build-essential libnuma-dev libmnl-dev libelf-dev rdma-core dpkg-dev"

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
#   - vm at ip ${1} to install dpdk
# Effects:
#   - does NOT set up hugepages or modprobe (see other funcs)
#	- only installs dpdk on first IP provided
function Install_Dpdk() {
	if [ -z "${LIS_HOME}" -o -z "${DPDK_LINK}" -o -z "${DPDK_DIR}" ]; then
		LogErr "ERROR: LIS_HOME, DPDK_LINK, and DPDK_DIR must be defined before calling Install_Dpdk()"
		SetTestStateAborted
		exit 1
	fi

	if [ -z "${1}" ]; then
		LogErr "ERROR: Must supply ip of host to Install_Dpdk()"
		SetTestStateAborted
		exit 1
	fi

	CheckIP ${1}
	if [ $? -eq 1 ]; then
		LogErr "ERROR: must pass valid ip to Install_Dpdk()"
		SetTestStateAborted
		exit 1
	fi
	local install_ip=${1}
	LogMsg "Installing dpdk on ${install_ip}"

	local distro=$(detect_linux_distribution)$(detect_linux_distribution_version)
	Install_Dpdk_Dependencies $install_ip $distro

	install_from_ppa=false

	if [[ $DPDK_LINK =~ .tar ]]; then
		ssh ${install_ip} "mkdir ${DPDK_DIR}"
		ssh ${install_ip} "wget -O - ${DPDK_LINK} | tar -xJ -C ${DPDK_DIR} --strip-components=1"
	elif [[ $DPDK_LINK =~ ".git" ]] || [[ $DPDK_LINK =~ "git:" ]]; then
		ssh ${install_ip} "rm -rf ${DPDK_DIR}" # LISA Pipelines don't always wipe old state
		ssh ${install_ip} "git clone ${DPDK_LINK} ${DPDK_DIR}"
	elif [[ $DPDK_LINK =~ "ppa:" ]]; then
		if [[ $distro != "ubuntu16.04" && $distro != "ubuntu18.04" ]]; then
			LogErr "PPAs are supported only on Debian based distros."
			SetTestStateAborted
			exit 1
		fi
		ssh "${install_ip}" "add-apt-repository ${DPDK_LINK} -y -s"
		ssh "${install_ip}" "apt-get update"
		install_from_ppa=true
	elif [[ $DPDK_LINK =~ "native" || $DPDK_LINK == "" ]]; then
		if [[ $distro != "ubuntu16.04" && $distro != "ubuntu18.04" ]]; then
			LogErr "Native installs are supported only on Debian based distros."
			SetTestStateAborted
			exit 1
		fi
		ssh "${install_ip}" "sed -i '/deb-src/s/^# //' /etc/apt/sources.list"
		check_exit_status "Enable source repos on ${install_ip}" "exit"
		install_from_ppa=true
	else
		LogErr "DPDK source link not supported: '${DPDK_LINK}'"
		SetTestStateAborted
		exit 1
	fi

	if [[ $install_from_ppa == true ]]; then
		ssh "${install_ip}" "apt install -y dpdk dpdk-dev"
		check_exit_status "Install DPDK from ppa ${DPDK_LINK} on ${install_ip}" "exit"
		ssh "${install_ip}" "apt-get source dpdk"
		check_exit_status "Get DPDK sources from ppa on ${install_ip}" "exit"

		dpdk_version=$(ssh "${install_ip}" "dpkg -s 'dpdk' | grep 'Version' | head -1 | awk '{print \$2}' | awk -F- '{print \$1}'")
		dpdk_source="dpdk_${dpdk_version}.orig.tar.xz"
		dpdkSrcDir="dpdk-${dpdk_version}"

		ssh "${install_ip}" "tar xf $dpdk_source"
		check_exit_status "Get DPDK sources from ppa on ${install_ip}" "exit"
		ssh "${install_ip}" "mv ${dpdkSrcDir} ${DPDK_DIR}"
	fi

	LogMsg "dpdk source on ${install_ip} at ${DPDK_DIR}"

	LogMsg "MLX_PMD flag enabling on ${install_ip}"
	ssh ${install_ip} "cd ${LIS_HOME}/${DPDK_DIR} && make config T=x86_64-native-linuxapp-gcc"
	ssh ${install_ip} "sed -ri 's,(MLX._PMD=)n,\1y,' ${LIS_HOME}/${DPDK_DIR}/build/.config"

	if type Dpdk_Configure > /dev/null; then
		echo "Calling testcase provided Dpdk_Configure(install_ip) on ${install_ip}"
		ssh ${install_ip} ". constants.sh; . utils.sh; . dpdkUtils.sh; cd ${LIS_HOME}/${DPDK_DIR}; $(typeset -f Dpdk_Configure); Dpdk_Configure ${install_ip}"
	fi

	ssh ${install_ip} "cd ${LIS_HOME}/${DPDK_DIR} && make -j"
	ssh ${install_ip} "cd ${LIS_HOME}/${DPDK_DIR} && make install"

	LogMsg "Finished installing dpdk on ${install_ip}"
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

	cmd="$(Create_Testpmd_Cmd ${2} ${3} ${4} ${5})"
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

	if [ -z "${DPDK_DIR}" ]; then
		LogErr "ERROR: DPDK_DIR must be defined before calling Create_Testpmd_Cmd()"
		SetTestStateAborted
		exit 1
	fi

	local core="${1}"
	local busaddr="${2}"
	local iface="${3}"
	local mode="${4}"

	# partial strings to concat
	local testpmd="${LIS_HOME}/${DPDK_DIR}/build/app/testpmd"
	local eal_opts="-l 0-${core} -w ${busaddr} --vdev='net_vdev_netvsc0,iface=${iface}' --"
	local testpmd_opts0="--port-topology=chained --nb-cores ${core} --txq ${core} --rxq ${core}"
	local testpmd_opts1="--mbcache=512 --txd=4096 --rxd=4096 --forward-mode=${mode} --stats-period 1 --tx-offloads=0x800e"

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
	sed -i "234i ${port_code}" app/test-pmd/txonly.c
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
	if [ -z "${1}" -o ]; then
		LogErr "ERROR: must provide dest ip to Testpmd_Macfwd_To_Dest()"
		SetTestStateAborted
		exit 1
	fi

	local ptr_code="struct ipv4_hdr *ipv4_hdr;"
	local offload_code="ol_flags |= PKT_TX_IP_CKSUM; ol_flags |= PKT_TX_IPV4;"
	local dst_addr=$(echo ${1} | sed 'y/\./,/')
	local dst_addr_code="ipv4_hdr = rte_pktmbuf_mtod_offset(mb, struct ipv4_hdr *, sizeof(struct ether_hdr)); ipv4_hdr->dst_addr = rte_be_to_cpu_32(IPv4(${dst_addr}));"

	sed -i "53i ${ptr_code}" app/test-pmd/macfwd.c
	sed -i "90i ${offload_code}" app/test-pmd/macfwd.c
	sed -i "101i ${dst_addr_code}" app/test-pmd/macfwd.c
}

function Get_DPDK_Version() {
	meson_config_path="${1}/meson.build"
	dpdk_version=$(grep -m 1 "version:" $meson_config_path | awk '{print $2}' | tr -d "\`'\,")
	echo $dpdk_version
}