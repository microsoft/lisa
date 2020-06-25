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

readonly dir_list=(/opt/microsoft/dependency-agent /var/opt/microsoft/dependency-agent /etc/opt/microsoft/dependency-agent /lib/microsoft-dependency-agent /etc/init.d/microsoft-dependency-agent)

readonly da_pid_file="/etc/opt/microsoft/dependency-agent/config/DA_PID"
readonly uninstaller="/opt/microsoft/dependency-agent/uninstall"

function test_case_cleanup(){
    [ -f "$uninstaller" ] && eval $uninstaller

    rm -rf "${dir_list[@]}"

    # This can be a NOP if the test exits before calling generate_network_activity
    kill $network_activity_generator_pid

    LogMsg "Finished cleaning up test cases"
}

# Calls the cleanup function when interupted or exited
trap test_case_cleanup SIGINT EXIT SIGHUP SIGQUIT SIGTERM

function fail_test() {
    LogErr "$*"
    SetTestStateFailed
    exit 0
}

function verify_directory_exists() {
    failed_assertions=false
    for dir in "${dir_list[@]}"
    do
        if [ -d "$dir" ]; then
            LogErr "Directory $dir exists."
            failed_assertions=true
        fi
    done

    if $failed_assertions; then
        LogErr "Some/All directories exists"
        echo "$failed_assertions"
    fi
}

function verify_distro() {
    case $DISTRO in
        redhat* | centos* | suse* | debian* | ubuntu*)
            LogMsg "Supported Distro family: $DISTRO"
            ;;
        *)
            fail_test "Unsupported Distro family: $DISTRO"
            ;;
    esac
}

function verify_expected_file() {
    if [ ! -f "$1" ]; then
        fail_test "${1} doesn't exist."
    fi
}

function verify_da_pid() {
    [ ! -f $da_pid_file ] && fail_test "$da_pid_file does not exist."

    if x=$(sed -n '/^[1-9][0-9]*$/p;q' $da_pid_file); then
        if strings /proc/$x/cmdline | fgrep -q  -e "microsoft-dependency-agent-manager"; then
            LogMsg "PID matched"
        else
            fail_test "PID not matched"
        fi
    else
        fail_test "PID not found in DA_PID"
    fi
}

function check_prereqs() {
    LogMsg "Checking for preconditions"

    if [[ $EUID -ne 0 ]]; then
        fail_test "This script must be run as root"
    fi

    verify_distro

    directory_exists=$(verify_directory_exists)
    if [ "directory_exists" == "true" ]; then
        SetTestStateAborted
        exit 0
    fi

    LogMsg "Preconditions met"
}

function download_da_linux_installer() {
    LogMsg "Download Dependency Agent Linux installer"

    if ! curl -L https://aka.ms/dependencyagentlinux -o InstallDependencyAgent-Linux64.bin; then
        fail_test Download failed
    fi

    chmod +x InstallDependencyAgent-Linux64.bin
}

function verify_install_da() {
    LogMsg "Starting Install tests"

    ./InstallDependencyAgent-Linux64.bin -vme

    ret=$?
    if [ $ret -ne 0 ]; then
        fail_test "Install failed with exit code ${ret}"
    fi
    LogMsg "Dependency Agent installed successfully"

    verify_expected_file "$uninstaller"
    verify_expected_file "/etc/init.d/microsoft-dependency-agent"
    verify_expected_file "/var/opt/microsoft/dependency-agent/log/install.log"

    bin_version=$(./InstallDependencyAgent-Linux64.bin --version | awk '{print $5}')
    install_log_version=$(sed -n 's/^Dependency Agent version\.revision: //p' /var/opt/microsoft/dependency-agent/log/install.log)
    if [ "$bin_version" -ne "$install_log_version" ]; then
        fail_test "Version mismatch between bin version($bin_version) and install log version($install_log_version)"
    fi
    LogMsg "Version matches between bin version and install log version"

    LogMsg "Install tests passed successfully"
}

function verify_uninstall_da() {
    LogMsg "Starting uninstall tests"

    eval $uninstaller

    ret=$?
    if [ $ret -ne 0 ]; then
        fail_test "Uninstall failed with exit code ${ret}"
    else
        LogMsg "Uninstalled with exit code 0"
    fi

    directory_exists=$(verify_directory_exists)
    if [ "directory_exists" == "true" ]; then
        fail_test "Directory exists"
    fi

    LogMsg "Uninstall tests passed successfully"
}

function generate_network_activity() {
    LogMsg "Generate network activity"
    watch -n 5 curl https://microsoft.com &>/dev/null &
    network_activity_generator_pid=$!
}

function enable_disable_da(){
    LogMsg "Starting Enable/Disable DA tests"

    verify_install_da

    # Wait for 30s for DA to start running and check for service.log
    sleep 30
    verify_expected_file "/var/opt/microsoft/dependency-agent/log/service.log"

    # Check for service.log.1 file and confirm service.log.2 doesn't exist
    service_log_time=$(date -r /var/opt/microsoft/dependency-agent/log/service.log +%s)
    time_limit=$(($service_log_time + 60))
    if [ "$DISTRO" == "debian"*] || ["$DISTRO" == "ubuntu"* ]; then
        time_limit=$(($time_limit + 60))
    fi

    while [ ! -f "/var/opt/microsoft/dependency-agent/log/service.log.1" ]
    do
        current_time=$(date +%s)
        if [ $current_time -gt $time_limit]; then
            SetTestStateFailed
            return
        fi
        sleep 5
    done

    verify_expected_file "/var/opt/microsoft/dependency-agent/log/service.log.1"
    [ -f "/var/opt/microsoft/dependency-agent/log/service.log.2" ] && fail_test "/var/opt/microsoft/dependency-agent/log/service.log.2 exist."
    [ ! -c "/dev/msda" ] && fail_test "/dev/msda does not exist."

    # Check for "driver setup status=0" and "starting the dependency agent" in service.log.1 and service.log respectively
    ! grep -iq "driver setup status=0" /var/opt/microsoft/dependency-agent/log/service.log.1 && fail_test "driver setup status=0 not found"
    ! grep -iq "starting the dependency agent" /var/opt/microsoft/dependency-agent/log/service.log && fail_test starting the dependency agent not found

    # Wait for DA to be running and verify by checking for MicrosoftDependencyAgent.log
    sleep 60
    verify_expected_file "/var/opt/microsoft/dependency-agent/log/MicrosoftDependencyAgent.log"
    verify_da_pid

    # Wait for events and verify by checking for /var/opt/microsoft/dependency-agent/storage/*.bb files
    sleep 120
    ! ls /var/opt/microsoft/dependency-agent/storage/*.bb && fail_test "/var/opt/microsoft/dependency-agent/storage/*.bb does not exist."

    # Wait for more events and verify by checking for /var/opt/microsoft/dependency-agent/storage/*.hb files
    sleep 90
    ! ls /var/opt/microsoft/dependency-agent/storage/*.hb && fail_test "/var/opt/microsoft/dependency-agent/storage/*.hb does not exist."
    verify_da_pid

    dmesg_error=$(dmesg | fgrep -e BUG: -e "Modules linked in:" -e "Call Trace:​" -A 20)
    [ ! -z "$dmesg_error" ] && fail_test "$dmesg_error"

    verify_uninstall_da

    LogMsg "Enable/Disable DA tests passed successfully"
}

function test_case_install_uninstall_da(){
    LogMsg "Starting Test Case 1: Install/Uninstall DA"
    verify_install_da
    verify_uninstall_da
}

function test_case_enable_disable_da(){
    LogMsg "Starting Test Case 2: Enable/Disable DA"
    generate_network_activity
    enable_disable_da
}

check_prereqs
download_da_linux_installer
test_case_install_uninstall_da
test_case_enable_disable_da

LogMsg "Validate DA tests completed"
SetTestStateCompleted
exit 0
