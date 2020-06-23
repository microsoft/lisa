#!/usr/bin/env bash
#######################################################################
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# validate-da.sh
# Description:
#    Validate the installation and uninstallation of the Dependency Agent.
#    Validate the enable and disable of the Dependency Agent.
#######################################################################

set -e
set -x

# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Get distro information
GetDistro

dir_list=(/opt/microsoft/dependency-agent /var/opt/microsoft/dependency-agent /etc/opt/microsoft/dependency-agent /lib/microsoft-dependency-agent /etc/init.d/microsoft-dependency-agent)
supported_distro_list=(redhat centos suse debian ubuntu)

readonly da_pid_file="/etc/opt/microsoft/dependency-agent/config/DA_PID"

function test_case_cleanup(){
    /opt/microsoft/dependency-agent/uninstall

    for dir in "${dir_list[@]}"
    do
        rm -rf $dir
    done

    kill $watch_pid

    LogMsg "Finished cleaning up test cases"
}

# Calls the cleanup function when interupted or exited
trap test_case_cleanup SIGINT EXIT

function verify_directory() {
    failed_assertions=0
    for dir in "${dir_list[@]}"
    do
        [ -d $dir ] && LogErr "Directory $dir exists." && SetTestStateFailed && failed_assertions=$[[failed_assertions+1]]
    done

    if ["$failed_assertions" -gt 0]; then
        LogErr "Some/All directories exists"
        SetTestStateFailed
        exit 0
    fi
}

function verify_distro() {
    LogMsg "Current distro: $DISTRO"
    for distro in "${supported_distro_list[@]}"
    do
        if [[ "$distro"* == $DISTRO ]]; then
        LogMsg "Supported Distro family"
        break
    else
        LogErr "Unsupported Distro family"
        SetTestStateSkipped
        exit 0
    done
}

function verify_da_pid() {
    [ ! -f $da_pid_file ] && LogErr "$da_pid_file does not exist." && SetTestStateFailed && exit 0

    if x=$(sed -n '/^[1-9][0-9]*$/p;q' $da_pid_file); then
        strings /proc/$x/cmdline | grep "microsoft-dependency-agent-manager" && LogMsg "PID matched" || (LogErr "PID not matched" && SetTestStateFailed && exit 0)
    else
        LogErr "PID not found in DA_PID"
        SetTestStateFailed
        exit 0
    fi
}

function check_prereqs() {
    LogMsg "Checking for preconditions"

    if [[ $EUID -ne 0 ]]; then
        LogErr "This script must be run as root" 
        SetTestStateFailed
        exit 0
    fi

    verify_directory
    verify_distro

    LogMsg "Preconditions met"
}

function download_da_linux_installer() {
    LogMsg "Download Dependency Agent Linux installer"

    curl -L https://aka.ms/dependencyagentlinux -o InstallDependencyAgent-Linux64.bin

    chmod +x InstallDependencyAgent-Linux64.bin
}

function verify_install_da() {
    ./InstallDependencyAgent-Linux64.bin -vme

    ret=$?
    if [ $ret -ne 0 ]; then
        LogErr "Install failed with exit code ${ret}"
        SetTestStateFailed
        exit 0
    else
        LogMsg "Installed with exit code 0"
    fi

    [ ! -f "/opt/microsoft/dependency-agent/uninstall" ] && LogErr "/opt/microsoft/dependency-agent/uninstall does not exist." && SetTestStateFailed && exit 0
    [ ! -f "/etc/init.d/microsoft-dependency-agent" ] && LogErr "/etc/init.d/microsoft-dependency-agent does not exist." && SetTestStateFailed && exit 0
    [ ! -f "/var/opt/microsoft/dependency-agent/log/install.log" ] && LogErr "/var/opt/microsoft/dependency-agent/log/install.log does not exist." && SetTestStateFailed && exit 0

    bin_version=$(./InstallDependencyAgent-Linux64.bin --version | awk '{print $5}')
    install_log_version=$(sed -n 's/^Dependency Agent version\.revision: //p' /var/opt/microsoft/dependency-agent/log/install.log)
    if [ "$bin_version" -ne "$install_log_version" ]; then
        LogErr "Version mismatch between bin version($bin_version) and install log version($install_log_version)"
        SetTestStateFailed
        exit 0
    else
        LogMsg "Version matches between bin version and install log version"
    fi

    LogMsg "Install tests passed successfully"
}

function verify_uninstall_da() {
    /opt/microsoft/dependency-agent/uninstall

    ret=$?
    if [ $ret -ne 0 ]; then
        LogErr "Uninstall failed with exit code ${ret}"
        SetTestStateFailed
        exit 0
    else
        LogMsg "Uninstalled with exit code 0"
    fi

    verify_directory

    LogMsg "Uninstall tests passed successfully"
}

function generate_network_activity() {
    LogMsg "Generate network activity"
    watch -n 5 curl https://microsoft.com &>/dev/null &
    watch_pid=$!
}

function enable_disable_da(){
    verify_install_da

    # Wait for 30s and check for service.log
    sleep 30
    [ ! -f "/var/opt/microsoft/dependency-agent/log/service.log" ] && LogErr "/var/opt/microsoft/dependency-agent/log/service.log does not exist." && SetTestStateFailed && exit 0

    # Check for service.log.1 file and confirm service.log.2 doesn't exist
    service_log_time=$(date -r /var/opt/microsoft/dependency-agent/log/service.log +%s)
    time_limit=$(($service_log_time + 120))
    while [ ! -f "/var/opt/microsoft/dependency-agent/log/service.log.1" ]
    do
        current_time=$(date +%s)
        if [ $current_time -gt $time_limit]; then
            SetTestStateFailed
            return
        fi
        sleep 5
    done

    [ ! -f "/var/opt/microsoft/dependency-agent/log/service.log.1" ] && LogErr "/var/opt/microsoft/dependency-agent/log/service.log.1 does not exist." && SetTestStateFailed && exit 0
    [ -f "/var/opt/microsoft/dependency-agent/log/service.log.2" ] && LogErr "/var/opt/microsoft/dependency-agent/log/service.log.2 exist." && SetTestStateFailed && exit 0
    [ ! -c "/dev/msda" ] && LogErr "/dev/msda does not exist." && SetTestStateFailed && exit 0

    # Check for "driver setup status=0" and "starting the dependency agent" in service.log.1 and service.log respectively
    ! grep -iq "driver setup status=0" /var/opt/microsoft/dependency-agent/log/service.log.1 && LogErr "driver setup status=0 not found" && SetTestStateFailed && exit 0
    ! grep -iq "starting the dependency agent" /var/opt/microsoft/dependency-agent/log/service.log && LogErr "starting the dependency agent not found" && SetTestStateFailed && exit 0

    # Wait for DA to be running and verify by checking for MicrosoftDependencyAgent.log
    sleep 60
    [ ! -f "/var/opt/microsoft/dependency-agent/log/MicrosoftDependencyAgent.log" ] && LogErr "/var/opt/microsoft/dependency-agent/log/MicrosoftDependencyAgent.log does not exist." && SetTestStateFailed && exit 0
    verify_da_pid

    # Wait for events and verify by checking for /var/opt/microsoft/dependency-agent/storage/*.bb files
    sleep 120
    ! ls /var/opt/microsoft/dependency-agent/storage/*.bb && LogErr "/var/opt/microsoft/dependency-agent/storage/*.bb does not exist." && SetTestStateFailed && exit 0

    # Wait for more events and verify by checking for /var/opt/microsoft/dependency-agent/storage/*.hb files
    sleep 90
    ! ls /var/opt/microsoft/dependency-agent/storage/*.hb && LogErr "/var/opt/microsoft/dependency-agent/storage/*.hb does not exist." && SetTestStateFailed && exit 0
    verify_da_pid

    dmesg_error=$(dmesg | fgrep -e BUG: -e "Modules linked in:" -e "Call Trace:​" -A 20)
    [ ! -z "$dmesg_error" ] && LogErr "$dmesg_error" && SetTestStateFailed && exit 0

    verify_uninstall_da

    LogMsg "Enable/Disable DA tests passed successfully"
}

function test_case_install_uninstall_da(){
    LogMsg "Starting Test Case 1: Install/Uninstall DA"
    check_prereqs
    download_da_linux_installer
    verify_install_da
    verify_uninstall_da
}

function test_case_enable_disable_da(){
    LogMsg "Starting Test Case 2: Enable/Disable DA" 
    generate_network_activity
    enable_disable_da
}

function test_case_cleanup(){
    /opt/microsoft/dependency-agent/uninstall

    for dir in "${dir_list[@]}"
    do
        rm -rf $dir
    done

    kill $watch_pid

    LogMsg "Finished cleaning up test cases"
}

test_case_install_uninstall_da
test_case_enable_disable_da

LogMsg "Validate DA tests completed"
SetTestStateCompleted
exit 0
