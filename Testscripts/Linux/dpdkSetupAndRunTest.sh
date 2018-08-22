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
    if [ -z "${CLIENT}" -o -z "${SERVER}" ]; then
        LogErr "ERROR: CLIENT and SERVER must be defined in environment"
        SetTestStateAborted
        exit 1
    fi

    # work around for known issue of some distro's NICs not coming up with IP
    local distro=$(detect_linux_distribution)$(detect_linux_distribution_version)
    if [[ "${distro}" == "ubuntu18.04" || "${distro}" == "rhel7.5" ]]; then
        LogMsg "Running dhcp for ${distro}; known issue"
        local dhcp_cmd="dhclient eth1 eth2"
        ssh ${SERVER} ${dhcp_cmd}
        eval ${dhcp_cmd}
    fi

    sleep 5

    local client_ips=($(ssh ${CLIENT} "hostname -I | awk '{print ${1}}'"))
    local server_ips=($(ssh ${SERVER} "hostname -I | awk '{print ${1}}'"))

    local server_ip1=${server_ips[1]}
    local client_ip1=${client_ips[1]}

    install_dpdk ${CLIENT} ${client_ip1} ${server_ip1} &
    local client_install_pid=$!

    install_dpdk ${SERVER} ${server_ip1} ${client_ip1}

    wait ${client_install_pid}

    LogMsg "Setting up Hugepages and modprobing drivers"
    hugepage_setup ${SERVER}
    modprobe_setup ${SERVER}
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
mkdir ${LOG_DIR}

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

tar -cvzf vmTestcaseLogs.tar.gz ${LOG_DIR}

LogMsg "dpdkSetupAndRunTest completed!"
SetTestStateCompleted