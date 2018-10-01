#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#############################################################################
#
# dpdkSetupAndRunTest.sh
# Description:
#   This script is employed by DPDK-TEMPLATE.ps1 to set up dpdk and run
#   user provided test cases.
#
#############################################################################

function dpdk_setup() {
    if [ -z "${IP_ADDRS}" ]; then
        LogErr "ERROR: IP_ADDRS must be defined in environment"
        SetTestStateAborted
        exit 1
    fi

    local ip
    for ip in $IP_ADDRS; do
        install_dpdk ${ip} &
        local pids="$pids $!"
    done
    wait $pids

    for ip in $IP_ADDRS; do
        hugepage_setup ${ip} &
        local pids="$pids $!"
    done
    wait $pids

    for ip in $IP_ADDRS; do
        modprobe_setup ${ip} &
        local pids="$pids $!"
    done
    wait $pids
    sleep 2
}

# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!" | tee ${HOME}/TestExecutionError.log
    echo "TestAborted" > ${HOME}/state.txt
    exit 1
}

. dpdkUtils.sh || {
    LogErr "ERROR: unable to source dpdkUtils.sh!"
    SetTestStateAborted
    exit 1
}

# Source constants file and initialize most common variables
UtilsInit
LOG_DIR="${LIS_HOME}/logdir"
mkdir -p ${LOG_DIR}

# constants.sh is now loaded; load user provided scripts
for file in ${USER_FILES}; do
    source_script "${LIS_HOME}/${file}"
done

# error check here so on failure don't waste time setting up dpdk
if ! type run_testcase > /dev/null; then
    LogErr "ERROR: missing run_testcase function"
    SetTestStateAborted
    exit 1
fi

LogMsg "Starting DPDK Setup"
dpdk_setup

LogMsg "Calling testcase provided run function"
run_testcase

LogMsg "tar -cvzf ${LIS_HOME}/vmTestcaseLogs.tar.gz ${LOG_DIR}"
tar -cvzf ${LIS_HOME}/vmTestcaseLogs.tar.gz ${LOG_DIR}

LogMsg "dpdkSetupAndRunTest completed!"
SetTestStateCompleted