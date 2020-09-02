#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# This script installs XDP dump application

repo_url="https://github.com/LIS/bpf-samples.git"

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

            ssh ${install_ip} "wget -o - https://apt.llvm.org/llvm-snapshot.gpg.key | sudo apt-key add -"
            ssh ${install_ip} "apt-add-repository \"${REPO_NAME}\""
            LogMsg "INFO: Updating apt repos with (${REPO_NAME})"
            ssh ${install_ip} ". utils.sh && CheckInstallLockUbuntu && update_repos"
            ssh ${install_ip} ". utils.sh && CheckInstallLockUbuntu && install_package \"clang llvm libelf-dev build-essential libbpfcc-dev\""
            ssh ${install_ip} ". utils.sh && CheckInstallLockUbuntu && Update_Kernel"

            if [ $? -ne 0 ]; then
                LogErr "ERROR: Failed to install required packages on ${DISTRO_STRING}"
                SetTestStateFailed
                exit 1
            fi
        ;;
        rhel)
            yum install -y --nogpgcheck git llvm clang elfutils-devel make
            if [ $? -ne 0 ]; then
                LogErr "ERROR: Failed to install required packages on ${DISTRO_STRING}"
                SetTestStateFailed
                exit 1
            fi
        ;;
        * )
            LogErr "Distribution (${DISTRO_NAME}) is not supported by this script."
            SetTestStateSkipped
            exit 1
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
    ssh ${install_ip} "git clone --recurse-submodules ${repo_url}"
    ssh ${install_ip} "cd bpf-samples/xdpdump && make"
    check_exit_status "xdpdump build on ${install_ip}" "exit"

    LogMsg "XDPDump is installed on ${install_ip} successfully"
}

# Run XDPDUMP application for 10 seconds
# example: Run_XDPDump 10.0.0.1 eth1
function Run_XDPDump {
    if [ -z "${1}" -o -z "${2}" ]; then
        LogErr "ERROR: must provide install ip and NIC Name to Run_XDPDump"
        SetTestStateAborted
        exit 1
    fi

    local install_ip="${1}"
    local nic_name="${2}"

    # https://lore.kernel.org/lkml/1579558957-62496-3-git-send-email-haiyangz@microsoft.com/t/
    LogMsg "XDP program cannot run with LRO (RSC) enabled, disable LRO before running XDP"
    ssh ${install_ip} "ethtool -K ${nic_name} lro off"
    LogMsg "$(date): Starting xdpdump for 10 seconds"
    ssh ${install_ip} "cd bpf-samples/xdpdump && timeout 10 ./xdpdump -i ${nic_name} > ~/xdpdumpout.txt 2>&1"
    check_exit_status "$(date): run xdpdump on ${install_ip}" "exit"

    LogMsg "Executing command ssh ${install_ip} 'tail -1 ~/xdpdumpout.txt'"
    test_out="$(ssh ${install_ip} 'tail -1 ~/xdpdumpout.txt')"
    LogMsg "Output of last command : ${test_out}"
    all_output="$(ssh ${install_ip} 'cat ~/xdpdumpout.txt')"
    LogMsg "Output timeout 10 ./xdpdump -i ${nic_name} - ${all_output}"
    if [[ $test_out == *"unloading xdp"* ]]; then
        LogMsg "XDP Dump Successfully ran on ${install_ip}"
    else
        LogErr "There was an Error XDP Dump. Please check xdpdumpout.txt"
        SetTestStateFailed
        exit 1
    fi
}

# Check if kernel supports XDP or not
function check_xdp_support {
    if [ -z "${1}" -o -z "${2}" ]; then
        LogErr "ERROR: must provide install ip and NIC Name to Run_XDPDump"
        SetTestStateAborted
        exit 0
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
        exit 1
    fi
}

UTIL_FILE="./utils.sh"

# Source utils.sh
. ${UTIL_FILE} || {
    echo "ERROR: unable to source ${UTIL_FILE}!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit
# Script start from here
LogMsg "*********INFO: Script execution Started********"
if [ -z ${ip} ] && [ ! -z "${1}" ]; then
    CheckIP ${1}
    ip=${1}
    LogMsg "IP : ${ip}"
fi

if [ -z ${nicName}] && [ ! -z "${2}" ]; then
    nicName=${2}
    LogMsg "nicName: ${2}"
fi

LogMsg "vm : eth0 : ${ip}"

check_xdp_support ${ip} ${nicName}

LogMsg "Installing XDP Dependencies on ${ip}"
Install_XDP_Dependencies ${ip}

LogMsg "Installing XDP Dump on ${ip}"
Install_XDPDump ${ip}

LogMsg "Run XDP Dump on ${ip}"
Run_XDPDump ${ip} ${nicName}

# check xdpdumpout.txt content for error
SetTestStateCompleted
LogMsg "*********INFO: XDP setup completed*********"
exit 0
