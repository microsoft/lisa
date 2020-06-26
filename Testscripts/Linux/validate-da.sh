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

readonly da_installer="InstallDependencyAgent-Linux64.bin"
readonly uninstaller="/opt/microsoft/dependency-agent/uninstall"

readonly da_pid_file="/etc/opt/microsoft/dependency-agent/config/DA_PID"
readonly da_log_dir="/var/opt/microsoft/dependency-agent/log"
readonly da_storage_dir="/var/opt/microsoft/dependency-agent/storage"

function test_case_cleanup(){
    [ -f $uninstaller ] && $uninstaller

    rm -f "$da_installer"

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

function check_da_directories_exist() {
    failed_assertions=false
    for dir in "${dir_list[@]}"
    do
        if [ -d "$dir" ]; then
            LogErr "Directory $dir exists."
            failed_assertions=true
        fi
    done

    if $failed_assertions; then
        LogErr "Some directories exists"
        $failed_assertions
    fi
}

function verify_distro() {
    case $DISTRO in
        redhat* | centos* | suse*)
            readonly enable_timeout=60 
            LogMsg "Supported Distro family: $DISTRO"
            ;;
        debian* | ubuntu*)
            readonly enable_timeout=120
            LogMsg "Supported Distro family: $DISTRO"
            ;;
        *)
            LogMsg "Unsupported Distro family: $DISTRO"
            SetTestStateSkipped
            exit 0
            ;;
    esac
}

function verify_expected_file() {
    if [ ! -f "$1" ]; then
        fail_test "${1} doesn't exist."
    fi
}

function verify_da_pid() {
    if [ ! -f $da_pid_file ]; then
        fail_test "$da_pid_file does not exist."
    fi

    if ! x=$(sed -n "/^[1-9][0-9]*$/p;q" $da_pid_file); then
        fail_test "PID not found in DA_PID"
    else
        if strings /proc/$x/cmdline | fgrep -q  -e "microsoft-dependency-agent-manager"; then
            LogMsg "PID matched"
        else
            fail_test "PID not matched"
        fi
    fi
}

function check_prereqs() {
    LogMsg "Checking for preconditions"

    if [ $EUID -ne 0 ]; then
        LogErr "This script must be run as root: $EUID"
        SetTestStateAborted
        exit 0
    fi

    verify_distro

    if check_da_directories_exist; then
        SetTestStateAborted
        exit 0
    fi

    LogMsg "Preconditions met"
}

function download_da_linux_installer() {
    LogMsg "Download Dependency Agent Linux installer"

    if ! curl -L https://aka.ms/dependencyagentlinux -o "$da_installer"; then
        fail_test Download failed
    fi

    chmod +x "$da_installer"
}

function verify_install_da() {
    LogMsg "Starting Install tests"

    ./"$da_installer" -vme

    ret=$?
    if [ $ret -ne 0 ]; then
        fail_test "Install failed with exit code ${ret}"
    fi
    LogMsg "Dependency Agent installed successfully"

    verify_expected_file "$uninstaller"
    verify_expected_file "/etc/init.d/microsoft-dependency-agent"
    verify_expected_file "$da_log_dir/install.log"

    bin_version=$(./"$da_installer" --version | awk "{print $5}")
    install_log_version=$(sed -n "s/^Dependency Agent version\.revision: //p" $da_log_dir/install.log)
    if [ "$bin_version" -ne "$install_log_version" ]; then
        fail_test "Version mismatch between bin version($bin_version) and install log version($install_log_version)"
    fi
    LogMsg "Version matches between bin version and install log version"

    LogMsg "Install tests completed"
}

function verify_uninstall_da() {
    LogMsg "Starting uninstall tests"

    $uninstaller

    ret=$?
    if [ $ret -ne 0 ]; then
        fail_test "Uninstall failed with exit code ${ret}"
    else
        LogMsg "Uninstalled with exit code 0"
    fi

    if check_da_directories_exist; then
        fail_test "Directory exists"
    fi

    LogMsg "Uninstall tests completed"
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
    verify_expected_file "$da_log_dir/service.log"

    # Check for service.log.1 file and confirm service.log.2 doesn't exist
    service_log_time=$(date -r $da_log_dir/service.log +%s)
    time_limit=$(($service_log_time + $enable_timeout))

    while [ ! -f "$da_log_dir/service.log.1" ]
    do
        current_time=$(date +%s)
        if [ $current_time -gt $time_limit]; then
            fail_test "Exceeded time limit to check service.log.1 file"
        fi
        sleep 5
    done

    verify_expected_file "$da_log_dir/service.log.1"
    
    if [ -f "$da_log_dir/service.log.2" ]; then
        fail_test "$da_log_dir/service.log.2 exist."
    fi
    
    if [ ! -c "/dev/msda" ]; then 
        fail_test "/dev/msda does not exist."
    fi
    # Check for "driver setup status=0" and "starting the dependency agent" in service.log.1 and service.log respectively
    if ! grep -iq "driver setup status=0" $da_log_dir/service.log.1; then
        fail_test "driver setup status=0 not found"
    fi

    if ! grep -iq "starting the dependency agent" $da_log_dir/service.log; then
        fail_test "starting the dependency agent not found"
    fi

    # Wait for DA to be running and verify by checking for MicrosoftDependencyAgent.log
    sleep 60
    verify_expected_file "$da_log_dir/MicrosoftDependencyAgent.log"
    verify_da_pid

    # Wait for events and verify by checking for /var/opt/microsoft/dependency-agent/storage/*.bb files
    sleep 120
    if ! ls $da_storage_dir/*.bb>/dev/null; then
        fail_test "$da_storage_dir/*.bb does not exist."
    fi

    # Wait for more events and verify by checking for /var/opt/microsoft/dependency-agent/storage/*.hb files
    sleep 90
    if ! ls $da_storage_dir/*.hb>/dev/null; then
        fail_test "$da_storage_dir/*.hb does not exist."
    fi
    verify_da_pid

    dmesg_error=$(dmesg | fgrep -e BUG: -e "Modules linked in:" -e "Call Trace:​" -A 20)
    if [ ! -z "$dmesg_error" ]; then
        fail_test "$dmesg_error"
    fi

    verify_uninstall_da

    LogMsg "Enable/Disable DA tests completed"
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
