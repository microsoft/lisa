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

dpdkMulticoreSetup() {
    # work around for known issue of some distro's NICs not coming up with IP
    local distro=$(detectDistro)$(detectDistroVersion)
    if [[ "${distro}" == "ubuntu18.04" || "${distro}" == "rhel7.5" ]]; then
        LogMsg "Running dhcp for ${distro}; known issue"
        local dhcpCMD="dhclient eth1 eth2"
        ssh ${server} $dhcpCMD
        eval $dhcpCMD
    fi

    sleep 5

    local clientIPs=($(ssh ${client} "hostname -I | awk '{print $1}'"))
    local serverIPs=($(ssh ${server} "hostname -I | awk '{print $1}'"))

    local serverNIC1ip=${serverIPs[1]}
    local serverNIC2ip=${serverIPs[2]}

    local clientNIC1ip=${clientIPs[1]}
    local clientNIC2ip=${clientIPs[2]}

    echo "server-vm : eth0 : ${server} : eth1 : ${serverNIC1ip} eth2 : ${serverNIC2ip}"
    echo "client-vm : eth0 : ${client} : eth1 : ${clientNIC1ip} eth2 : ${clientNIC2ip}"

    LogMsg "Installing DPDK on: ${client} and ${server}"
    installDPDK ${client} ${clientNIC1ip} ${serverNIC1ip} &
    local clientInstallPID=$!

    installDPDK ${server} ${serverNIC1ip} ${clientNIC1ip}

    wait $clientInstallPID

    LogMsg "Setting up Hugepages and modprobing drivers"
    hugePageSetup ${server}
    modprobeSetup ${server}
}

# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!" | tee ${LIS_HOME}/TestExecutionError.log
    echo "TestAborted" > ${LIS_HOME}/state.txt
    exit 1
}

. dpdkUtils.sh || {
    LogErr "ERROR: unable to source dpdkUtils.sh!"
    SetTestStateAborted
    exit 1
}

# Source constants file and initialize most common variables
UtilsInit
LOGDIR="${LIS_HOME}/logdir"
mkdir $LOGDIR

# constants.sh is now loaded; load user provided scripts
for file in $userFiles; do
    sourceScript "${LIS_HOME}/${file}"
done

# error check here so on failure don't waste time setting up dpdk
if ! type runTestcase > /dev/null; then
    LogErr "ERROR: missing runTestcase function"
    SetTestStateAborted
    exit 10
fi

LogMsg "Starting DPDK Setup"
dpdkMulticoreSetup

# calling user provided function
runTestcase

tar -cvzf vmTestcaseLogs.tar.gz $LOGDIR

LogMsg "dpdkSetupAndRunTest completed!"
SetTestStateCompleted