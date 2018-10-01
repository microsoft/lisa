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

# Helper function to install_dpdk()
# Requires:
#   - called only from install_dpdk()
#   - see install_dpdk() requires
#   - type [SRC | DST], install ip, and testpmd ip to configure as arguments in that order
function testpmd_ip_setup() {
    if [ -z "${1}" -o -z "${2}" -o -z "${3}" ]; then
        LogErr "ERROR: must provide ip type as SRC or DST, install ip, and testpmd ip to testpmd_ip_setup()"
        SetTestStateAborted
        exit 1
    fi

    local ip_type=${1}
    if [ "${ip_type}" != "SRC" -a "${ip_type}" != "DST" ]; then
        LogErr "ERROR: ip type invalid use SRC or DST testpmd_ip_setup()"
        SetTestStateAborted
        exit 1
    fi

    local install_ip=${2}
    local ip_for_testpmd=${3}

    local ip_arr=($(echo ${ip_for_testpmd} | sed "s/\./ /g"))
    local ip_addr="define IP_${ip_type}_ADDR ((${ip_arr[0]}U << 24) | (${ip_arr[1]} << 16) | ( ${ip_arr[2]} << 8) | ${ip_arr[3]})"
    local ip_config_cmd="sed -i 's/define IP_${ip_type}_ADDR.*/${ip_addr}/' ${LIS_HOME}/${dpdk_dir}/app/test-pmd/txonly.c"
    LogMsg "ssh ${install_ip} ${ip_config_cmd}"
    ssh ${install_ip} ${ip_config_cmd}
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
    local ip_1_invalid=${?}
    local ip_2_invalid=0
    local ip_3_invalid=0

    if [ -n "${2}" ]; then
        CheckIP ${2}
        ip_2_invalid=${?}
    fi

    if [ -n "${3}" ]; then
        CheckIP ${3}
        ip_3_invalid=${?}
    fi

    if [ ${ip_1_invalid} -eq 1 -o ${ip_2_invalid} -eq 1 -o ${ip_3_invalid} -eq 1 ]; then
        LogErr "ERROR: must provide valid IPs to install_dpdk()"
        SetTestStateAborted
        exit 1
    fi

    local install_ip=${1}
    local src_ip=${2}
    local dst_ip=${3}
    LogMsg "Installing dpdk on ${install_ip}"

    # when available update to dpdk latest
    if [ -z "${DPDK_LINK}" ]; then
        DPDK_LINK="https://fast.dpdk.org/rel/dpdk-18.08.tar.xz"
        LogMsg "DPDK_LINK missing from environment; using ${DPDK_LINK}"
    fi

    local distro=$(detect_linux_distribution)$(detect_linux_distribution_version)
    install_dpdk_dependencies $install_ip $distro

    if [[ $DPDK_LINK =~ .tar ]]; then
        local dpdk_dir="dpdk-$(echo ${DPDK_LINK} | grep -Po "(\d+\.)+\d+")"
        ssh ${install_ip} "wget -O - ${DPDK_LINK} | tar -xJ -C ${dpdk_dir} --strip-components=1"
    elif [[ $DPDK_LINK =~ ".git" ]] || [[ $DPDK_LINK =~ "git:" ]]; then
		local dpdk_dir="${DPDK_LINK##*/}"
		ssh ${install_ip} "git clone ${DPDK_LINK} ${dpdk_dir}"
	fi
    LogMsg "dpdk source on ${install_ip} at ${dpdk_dir}"
    
    if [ -n "${src_ip}" ]; then
        LogMsg "dpdk build with NIC SRC IP ${src_ip} ADDR on ${install_ip}"
        testpmd_ip_setup "SRC" ${install_ip} ${src_ip}
    fi

    if [ -n "${dst_ip}" ]; then
        LogMsg "dpdk build with NIC DST IP ${dst_ip} ADDR on ${install_ip}"
        testpmd_ip_setup "DST" ${install_ip} ${dst_ip}
    fi

    LogMsg "MLX_PMD flag enabling on ${install_ip}"
    ssh ${install_ip} "cd ${LIS_HOME}/${dpdk_dir} && make config T=x86_64-native-linuxapp-gcc"
    ssh ${install_ip} "sed -ri 's,(MLX._PMD=)n,\1y,' ${LIS_HOME}/${dpdk_dir}/build/.config"
    ssh ${install_ip} "cd ${LIS_HOME}/${dpdk_dir} && make -j"
    ssh ${install_ip} "cd ${LIS_HOME}/${dpdk_dir} && make install"

    LogMsg "Finished installing dpdk on ${install_ip}"
}