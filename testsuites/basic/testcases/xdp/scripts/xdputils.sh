#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# This script holds commons function used in XDP Testcases

pktgenResult=""
repo_url="https://github.com/LIS/bpf-samples.git"

function get_vf_name() {
    local nicName=$1
    local ignoreIF=$(ip route | grep default | awk '{print $5}')
    local interfaces=$(ls /sys/class/net | grep -v lo | grep -v ${ignoreIF})
    local synthIFs=""
    local vfIFs=""
    local interface
    for interface in ${interfaces}; do
        # alternative is, but then must always know driver name
        # readlink -f /sys/class/net/<interface>/device/driver/
        local bus_addr=$(ethtool -i ${interface} | grep bus-info | awk '{print $2}')
        if [ -z "${bus_addr}" ]; then
            synthIFs="${synthIFs} ${interface}"
        else
            vfIFs="${vfIFs} ${interface}"
        fi
    done

    local vfIF
    local synthMAC=$(ip link show $nicName | grep ether | awk '{print $2}')
    for vfIF in ${vfIFs}; do
        local vfMAC=$(ip link show ${vfIF} | grep ether | awk '{print $2}')
        # single = is posix compliant
        if [ "${synthMAC}" = "${vfMAC}" ]; then
            echo "${vfIF}"
            break
        fi
    done
}

function calculate_packets_drop(){
    local nicName=$1
    local vfName=$(get_vf_name ${nicName})
    local synthDrop=0
    IFS=$'\n' read -r -d '' -a xdp_packet_array < <(ethtool -S $nicName | grep 'xdp' | cut -d':' -f2)
    for i in "${xdp_packet_array[@]}";
    do
        synthDrop=$((synthDrop+i))
    done
    vfDrop=$(ethtool -S $vfName | grep rx_xdp_drop | cut -d':' -f2)
    if [ $? -ne 0 ]; then
        echo "$((synthDrop))"
    else
        echo "$((vfDrop + synthDrop))"
    fi
}

function calculate_packets_forward(){
    local nicName=$1
    local vfName=$(get_vf_name ${nicName})
    vfForward=$(ethtool -S $vfName | grep rx_xdp_tx_xmit | cut -d':' -f2)
    echo "$((vfForward))"
}

function download_pktgen_scripts(){
    local ip=$1
    local dir=$2
    local cores=$3
    if [ "${cores}" = "multi" ];then
        ssh $ip "wget https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/plain/samples/pktgen/pktgen_sample05_flow_per_thread.sh?h=v5.7.8 -O ${dir}/pktgen_sample.sh"
    else
        ssh $ip "wget https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/plain/samples/pktgen/pktgen_sample01_simple.sh?h=v5.7.8 -O ${dir}/pktgen_sample.sh"
    fi
    ssh $ip "wget https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/plain/samples/pktgen/functions.sh?h=v5.7.8 -O ${dir}/functions.sh"
    ssh $ip "wget https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/plain/samples/pktgen/parameters.sh?h=v5.7.8 -O ${dir}/parameters.sh"
    ssh $ip "chmod +x ${dir}/*.sh"
}

function start_pktgen(){
    local sender=$1
    local cores=$2
    local pktgenDir=$3
    local nicName=$4
    local forwarderSecondMAC=$5
    local forwarderSecondIP=$6
    local packetCount=$7
    if [ "${cores}" = "single" ];then
        startCommand="cd ${pktgenDir} && ./pktgen_sample.sh -i ${nicName} -m ${forwarderSecondMAC} -d ${forwarderSecondIP} -v -n${packetCount}"
        LogMsg "Starting pktgen on sender: $startCommand"
        ssh ${sender} "modprobe pktgen; lsmod | grep pktgen"
        result=$(ssh ${sender} "${startCommand}")
    else
        startCommand="cd ${pktgenDir} && ./pktgen_sample.sh -i ${nicName} -m ${forwarderSecondMAC} -d ${forwarderSecondIP} -v -n${packetCount} -t8"
        LogMsg "Starting pktgen on sender: ${startCommand}"
        ssh ${sender} "modprobe pktgen; lsmod | grep pktgen"
        result=$(ssh ${sender} "${startCommand}")
    fi
    pktgenResult=$result
    LogMsg "pktgen result: $pktgenResult"
}

function start_xdpdump(){
    local ip=$1
    local nicName=$2
    xdpdumpCommand="cd bpf-samples/xdpdump && ./xdpdump -i ${nicName} > ~/xdpdumpout_${ip}.txt"
    LogMsg "Starting xdpdump on ${ip} with command: ${xdpdumpCommand}"
    ssh -f ${ip} "sh -c '${xdpdumpCommand}'"
}

# Helper Function
# Install dependencies for XDP
function Install_XDP_Dependencies(){
    if [ -z "${1}" ]; then
        LogErr "ERROR: must provide install ip to Install_XDP_Dependencies()"
        SetTestStateAborted
        exit 1
    fi

    local install_ip="${1}"

    CheckIP ${install_ip}
    if [ $? -eq 1 ]; then
        LogErr "ERROR: must pass valid ip to Install_XDP_Dependencies()"
        SetTestStateAborted
        exit 1
    fi

    LLVM_VERSION="-6.0"
    DISTRO_STRING="${DISTRO_NAME}_${DISTRO_VERSION}"
    # check distro version
    case "$DISTRO_NAME" in
        ubuntu)
            if [[ "${DISTRO_VERSION}" == "16.04" ]]; then
                LogErr "Distribution (${DISTRO_STRING}) not supported by libbpfcc"
                SetTestStateSkipped
                exit 1
            fi

            source /etc/os-release
            REPO_NAME="deb http://apt.llvm.org/$UBUNTU_CODENAME/   llvm-toolchain-$UBUNTU_CODENAME$LLVM_VERSION  main"

            Run_SSHCommand ${install_ip} "wget -o - https://apt.llvm.org/llvm-snapshot.gpg.key | sudo apt-key add -"
            Run_SSHCommand ${install_ip} "apt-add-repository \"${REPO_NAME}\""
            LogMsg "INFO: Updating apt repos with (${REPO_NAME})"
            Run_SSHCommand ${install_ip} ". utils.sh && CheckInstallLockUbuntu && update_repos"
            Run_SSHCommand ${install_ip} ". utils.sh && CheckInstallLockUbuntu && install_package \"clang llvm libelf-dev build-essential libbpfcc-dev\""
            Run_SSHCommand ${install_ip} ". utils.sh && CheckInstallLockUbuntu && Update_Kernel"

            if [ $? -ne 0 ]; then
                LogErr "ERROR: Failed to install required packages on ${DISTRO_STRING}"
                SetTestStateFailed
                exit 1
            fi
        ;;
        rhel)
            Run_SSHCommand ${install_ip} "yum install -y --nogpgcheck git llvm clang elfutils-devel make"
            if [ $? -ne 0 ]; then
                LogErr "ERROR: Failed to install required packages on ${DISTRO_STRING}"
                SetTestStateFailed
                exit 3
            fi
        ;;
        * )
            LogErr "Distribution (${DISTRO_NAME}) is not supported by this script."
            SetTestStateSkipped
            exit 2
    esac
    LogMsg "XDP Dependecies installed successfully on (${DISTRO_STRING})."
}

# Install XDPDump
function Install_XDPDump(){
    if [ -z "${1}" ]; then
        LogErr "ERROR: must provide install ip to Install_XDPDump"
        SetTestStateAborted
        exit 1
    fi

    local install_ip="${1}"
    LogMsg "Cloning and building xdpdump"
    Run_SSHCommand ${install_ip} "git clone --recurse-submodules ${repo_url}"
    Run_SSHCommand ${install_ip} "cd bpf-samples/xdpdump && make"
    check_exit_status "xdpdump build on ${install_ip}" "exit"

    LogMsg "XDPDump is installed on ${install_ip} successfully"
}

# Check if kernel supports XDP or not
function check_xdp_support {
    if [ -z "${1}" -o -z "${2}" ]; then
        LogErr "ERROR: must provide install ip and NIC Name to check_xdp_support"
        SetTestStateAborted
        exit 1
    fi
    local install_ip="${1}"
    local nic_name="${2}"
    command="ethtool -S ${nic_name}  | grep xdp_drop | wc -l"
    xdp_counter="$(ssh ${install_ip} $command)"
    if [ $xdp_counter -gt 0 ]; then
        LogMsg "Kernel version supports XDP"
    else
        LogErr "Kernel Version does not support XDP"
        SetTestStateSkipped
        exit 2
    fi
}

function get_extra_synth_nic {
    local ignore_if=$(ip route | grep default | awk '{print $5}')
    local interfaces=$(ls /sys/class/net | grep -v lo | grep -v ${ignore_if})

    local synth_ifs=""
    for interface in ${interfaces}; do
        # alternative is, but then must always know driver name
        # readlink -f /sys/class/net/<interface>/device/driver/
        local bus_addr=$(ethtool -i ${interface} | grep bus-info | awk '{print $2}')
        if [ -z "${bus_addr}" ]; then
            synth_ifs="${synth_ifs} ${interface}"
        fi
    done
    echo "${synth_ifs}"
}