#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#

#############################################################################
#
# Description:
#
# This script contains all dpdk specific functions.
#
#############################################################################

# gets synthetic vf pairs by comparing MAC addresses.
#   will ignore the default route interface even if it has accelerated networking,
#   which should be the primaryNIC with pubilc ip to which you SSH
# recommend to capture output in array like so
#   pairs=($(getSyntheticVfPair))
#   then synthetic ${pairs[n]} maps to vf pci address ${pairs[n+1]}
#   when starting from zero i.e. index 1 and 2 have no relation
#   if captured output is empty then no VFs exist
function getSyntheticVfPairs() {
    all_ifs=$(ls /sys/class/net | grep -v lo)
    local ignore_if=$(ip route | grep default | awk '{print $5}')

    local synth_ifs=""
    local vf_ifs=""
    local interface
    for interface in $all_ifs; do
        if [ "${interface}" != "${ignore_if}" ]; then
            # alternative is, but then must always know driver name
            # readlink -f /sys/class/net/<interface>/device/driver/
            local bus_addr=$(ethtool -i $interface | grep bus-info | awk '{print $2}')
            if [ -z "${bus_addr}" ]; then
                synth_ifs="$synth_ifs $interface"
            else
                vf_ifs="$vf_ifs $interface"
            fi
        fi
    done

    local synth_if
    local vf_if
    for synth_if in $synth_ifs; do
        local synth_mac=$(ip link show $synth_if | grep ether | awk '{print $2}')

        for vf_if in $vf_ifs; do
            local vf_mac=$(ip link show $vf_if | grep ether | awk '{print $2}')
            # single = is posix compliant
            if [ "${synth_mac}" = "${vf_mac}" ]; then
                bus_addr=$(ethtool -i $vf_if | grep bus-info | awk '{print $2}')
                echo "${synth_if} ${bus_addr}"
            fi
        done
    done
}

# Requires:
#    UtilsInit has been called
# Effects:
#    Configures hugepages on local machine and IP if provided
function hugePageSetup() {
    local hugepageCMD="mkdir /mnt/huge; mount -t hugetlbfs nodev /mnt/huge && \
        echo 4096 | tee /sys/devices/system/node/node*/hugepages/hugepages-2048kB/nr_hugepages > /dev/null && grep Huge /proc/meminfo"

    eval $hugepageCMD
    if [ ! -z "${1}" ]; then
        CheckIP ${1}
        local res=$?
        if [ $res -eq 1 ]; then
            LogErr "ERROR: must pass valid ip to hugePageSetup"
            SetTestStateAborted
            exit 1
        fi
        ssh ${1} "${hugepageCMD}"
    fi
}

# Requires:
#    UtilsInit has been called
# Effects:
#    modprobes required mods for dpdk on local machine and IP if provided
function modprobeSetup() {
    local modprobeCMD="modprobe -a ib_uverbs"
    
    # known issue on sles15
    local distro=$(detect_linux_distribution)$(detect_linux_distribution_version)
    if [[ "${distro}" == "sles15" ]]; then
        modprobeCMD="$modprobeCMD mlx4_ib"
    fi

    eval $modprobeCMD
    if [ ! -z "${1}" ]; then
        CheckIP ${1}
        local res=$?
        if [ $res -eq 1 ]; then
            LogErr "ERROR: must pass valid ip to modprobeSetup"
            SetTestStateAborted
            exit 1
        fi
        ssh ${1} "${modprobeCMD}"
    fi
}

function sourceScript() {
    if [ -z "${1}" ]; then
        LogErr "ERROR: Must supply script name as 1st argument to sourceScript"
        SetTestStateAborted
        exit 1
    fi

    local file="${1}"
    if [ -e ${file} ]; then
        source ${file}
    else
        LogErr "ERROR: func sourceScript unable to source ${file} file"
        SetTestStateAborted
        exit 1
    fi
}

# Requires:
#   - basic environ (i.e. have called UtilsInit())
#   - ^ includes constants.sh which has dpdkSrcLink
#   - ${1} dpdk install target ip
#   - ${2} src ip for txonly.c
#   - ${3} dst ip
# Modifies:
#   - vm at ip ${1} to install dpdk with src ip ${2} to dst ip ${3}
# Effects:
#   - does NOT set up hugepages or modprobe (see other funcs)
#	- only installs dpdk on first IP provided
function installDPDK() {
    if [ -z "${LIS_HOME}" ]; then
        LogErr "ERROR: LIS_HOME must be defined before calling installDPDK"
        SetTestStateAborted
        exit 1
    fi

    if [ -z "${1}" -o -z "${2}" -o -z "${3}" ]; then
        LogErr "ERROR: Must supply ip of host to install DPDK on, then source ip of nic1, and finally dest ip of nic1"
        SetTestStateAborted
        exit 1
    fi

    CheckIP ${1}
    local ip1invalid=$?

    CheckIP ${2}
    local ip2invalid=$?

    CheckIP ${3}
    local ip3invalid=$?
    if [ $ip1invalid -eq 1 -o $ip2invalid -eq 1 -o $ip3invalid -eq 1 ]; then
        LogErr "ERROR: provided IPs to installDPDK must valid"
        SetTestStateAborted
        exit 1
    fi

    local srcIp=${2}
    local dstIp=${3}
    LogMsg "Configuring ${1} for DPDK test..."

    if [ -z "${dpdkSrcLink}" ]; then
        dpdkSrcLink="https://fast.dpdk.org/rel/dpdk-18.05.tar.xz"
        LogMsg "dpdkSrcLink missing from constants file; using $dpdkSrcLink"
    fi

    local dpdkSrcTar="${dpdkSrcLink##*/}"
    local dpdkVersion=$(echo $dpdkSrcTar | grep -Po "(\d+\.)+\d+")
    local DPDK_BUILD=x86_64-native-linuxapp-gcc

    local distro=$(detect_linux_distribution)$(detect_linux_distribution_version)
    if [[ "${distro}" == ubuntu* ]]; then
        if [[ "${distro}" == "ubuntu16.04" ]]; then
            LogMsg "Detected ubuntu16.04"
            ssh ${1} "add-apt-repository ppa:canonical-server/dpdk-azure -y"
        elif [[ "${distro}" == "ubuntu18.04" ]]; then 
            LogMsg "Detected ubuntu18.04"
        else
            LogErr "ERROR: unsupported ubuntu version for dpdk on Azure"
            SetTestStateAborted
            exit 1
        fi

        ssh ${1} "apt-get update"
        ssh ${1} "apt-get install -y librdmacm-dev librdmacm1 build-essential libnuma-dev"

    elif [[ "${distro}" == "rhel7.5" || "${distro}" == centos7.5* ]]; then
        LogMsg "Detected (rhel/centos)7.5"

        ssh ${1} "yum -y groupinstall 'Infiniband Support'"
        ssh ${1} "dracut --add-drivers 'mlx4_en mlx4_ib mlx5_ib' -f"
        ssh ${1} "yum install -y gcc kernel-devel-$(uname -r) numactl-devel.x86_64 librdmacm-devel"

    elif [[ "${distro}" == "sles15" ]]; then
        LogMsg "Detected sles15"

        local kernel=$(uname -r)
        if [[ "${kernel}" == *azure ]]; then
            ssh ${1} "zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install kernel-azure kernel-devel-azure gcc make libnuma-devel numactl librdmacm1 rdma-core-devel"
        else
            ssh ${1} "zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install kernel-default-devel gcc make libnuma-devel numactl librdmacm1 rdma-core-devel"
        fi
    else 
        LogErr "ERROR: unsupported distro for dpdk on Azure"
        SetTestStateAborted
        exit 1
    fi

    LogMsg "Installing DPDK from source file $dpdkSrcTar"
    ssh ${1} "wget $dpdkSrcLink -P /tmp"
    ssh ${1} "tar xvf /tmp/$dpdkSrcTar"
    local dpdkSrcDir=$(ssh ${1} "ls | grep dpdk- | grep -v \.sh")
    LogMsg "dpdk source on ${1} $dpdkSrcDir"

    LogMsg "dpdk build with NIC SRC IP $srcIp ADDR on ${1}"
    local srcIpArry=($(echo $srcIp | sed "s/\./ /g"))
    local srcIpAddrs="define IP_SRC_ADDR ((${srcIpArry[0]}U << 24) | (${srcIpArry[1]} << 16) | ( ${srcIpArry[2]} << 8) | ${srcIpArry[3]})"
    local srcIpConfigCmd="sed -i 's/define IP_SRC_ADDR.*/$srcIpAddrs/' $LIS_HOME/$dpdkSrcDir/app/test-pmd/txonly.c"
    LogMsg "ssh ${1} $srcIpConfigCmd"
    ssh ${1} $srcIpConfigCmd

    LogMsg "dpdk build with NIC DST IP $dstIp ADDR on ${1}"
    local dstIpArry=($(echo $dstIp | sed "s/\./ /g"))
    local dstIpAddrs="define IP_DST_ADDR ((${dstIpArry[0]}U << 24) | (${dstIpArry[1]} << 16) | (${dstIpArry[2]} << 8) | ${dstIpArry[3]})"
    local dstIpConfigCmd="sed -i 's/define IP_DST_ADDR.*/$dstIpAddrs/' $LIS_HOME/$dpdkSrcDir/app/test-pmd/txonly.c"
    LogMsg "ssh ${1} $dstIpConfigCmd"
    ssh ${1} $dstIpConfigCmd

    LogMsg "MLX_PMD flag enabling on ${1}"
    ssh ${1} "cd $LIS_HOME/$dpdkSrcDir && make config T=${DPDK_BUILD}"
    ssh ${1} "sed -ri 's,(MLX._PMD=)n,\1y,' $LIS_HOME/$dpdkSrcDir/build/.config"
    ssh ${1} "cd $LIS_HOME/$dpdkSrcDir && make -j"
    ssh ${1} "cd $LIS_HOME/$dpdkSrcDir && make install"

    LogMsg "Installed DPDK version on ${1} is ${dpdkVersion}"
}