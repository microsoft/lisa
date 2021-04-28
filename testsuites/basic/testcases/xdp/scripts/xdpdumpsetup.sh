#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# This script installs XDP dump application

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
    Run_SSHCommand ${install_ip} "ethtool -K ${nic_name} lro off"
    LogMsg "$(date): Starting xdpdump for 10 seconds"
    Run_SSHCommand ${install_ip} "cd bpf-samples/xdpdump && timeout 10 ./xdpdump -i ${nic_name} > ~/xdpdumpout.txt 2>&1"
    check_exit_status "$(date): run xdpdump on ${install_ip}" "exit"

    LogMsg "Executing command Run_SSHCommand ${install_ip} 'tail -1 ~/xdpdumpout.txt'"
    test_out="$(Run_SSHCommand ${install_ip} 'tail -1 ~/xdpdumpout.txt')"
    LogMsg "Output of last command : ${test_out}"
    all_output="$(Run_SSHCommand ${install_ip} 'cat ~/xdpdumpout.txt')"
    LogMsg "Output timeout 10 ./xdpdump -i ${nic_name} - ${all_output}"
    if [[ $test_out == *"unloading xdp"* ]]; then
        LogMsg "XDP Dump Successfully ran on ${install_ip}"
    else
        LogErr "There was an Error XDP Dump. Please check xdpdumpout.txt"
        SetTestStateFailed
        exit 1
    fi
}

UTIL_FILE="./utils.sh"
XDPUTIL_FILE="./xdputils.sh"
# Source utils.sh
. ${UTIL_FILE} || {
    echo "ERROR: unable to source ${UTIL_FILE}!"
    echo "TestAborted" > state.txt
    exit 1
}

# Source constants file and initialize most common variables
UtilsInit
# Source xdputils.sh
. ${XDPUTIL_FILE} || {
    LogMsg "ERROR: unable to source ${XDPUTIL_FILE}!"
    SetTestStateAborted
    exit 1
}
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
#nicName=$(get_extra_synth_nic)
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
