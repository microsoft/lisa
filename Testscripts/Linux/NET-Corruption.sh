#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
test_interface=eth1

function InstallNetcat {
    LogMsg "Installing netcat"
    SetTestStateRunning
    update_repos
    if [[ "$os_VENDOR" == "Red Hat" ]] || \
    [[ "$os_VENDOR" == "Fedora" ]] || \
    [[ "$os_VENDOR" == "CentOS" ]]; then
        package_name="nc"
    else
        package_name="netcat"
    fi
    install_package $package_name
    return 0
}


function ConfigInterface {
    CreateIfupConfigFile $test_interface "dhcp"
    sleep 5

    if [ $? -eq 0 ]; then
        ip_address=$(ip addr show | grep "inet\b" | grep -v '127.0.0.1' | awk '{print $2}' | cut -d/ -f1 | sed -n 2p)
        LogMsg "Successfully set IP address - ${ip_address}"
    else
        LogErr "The new interface doesn't have a valid IP"
        SetTestStateFailed
        exit 0
    fi

    # Disable reverse protocol filters
    sysctl -w net.ipv4.conf.all.rp_filter=0
    sysctl -w net.ipv4.conf.default.rp_filter=0
    sysctl -w net.ipv4.conf.eth0.rp_filter=0
    sysctl -w net.ipv4.conf.${test_interface}.rp_filter=0
    sleep 2

    #Check if ethtool exist and install it if not
    ethtool --version
    if [ $? -ne 0 ]; then
        install_package "ethtool"
    fi

    # Disable tcp segmentation offload
    ethtool -K $test_interface tso off
    ethtool -K $test_interface gso off

    return 0
}

# Main script body
filePath=$1
port=$2

# Convert eol
dos2unix utils.sh
# Source utils.sh
. utils.sh || {
    echo "unable to source utils.sh!"
    echo "TestAborted" >> state.txt
    exit 0
}
UtilsInit
GetOSVersion

if [ "${FILE_SIZE:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "Error : Parameter FILE_SIZE was not found"
    SetTestStateAborted
    exit 0
fi

if [ "${CORRUPTION:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "Error : Parameter CORRUPTION was not found"
    SetTestStateAborted
    exit 0
fi

InstallNetcat
if [ 0 -ne $? ]; then
    LogMsg "Unable to install netcat"
    SetTestStateFailed
    exit 0
fi

LogMsg "Creating new file of size ${FILE_SIZE}"
dd if=/dev/urandom of=$filePath bs=$FILE_SIZE count=1
if [ 0 -ne $? ]; then
    LogMsg "Unable to create file"
    SetTestStateFailed
    exit 0
fi

# Config interface and disable iptables
ConfigInterface
iptables -F
iptables -X
# Set corruption
tc qdisc add dev $test_interface root netem corrupt ${CORRUPTION}
if [ 0 -ne $? ]; then
    LogMsg "Unable to set corruption to ${CORRUPTION}"
    SetTestStateFailed
    exit 0
fi

LogMsg "Starting to listen on port 1234"
echo "nc -v -w 30 -l -p $port < $filePath &" > $3
chmod +x $3
SetTestStateCompleted
exit 0