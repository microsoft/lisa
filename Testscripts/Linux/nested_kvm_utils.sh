#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# nested_kvm_utils.sh
#
# Description:
#   common functions of nested kvm cases
# Dependency:
#   utils.sh
#######################################################################

. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 2
}

ICA_TESTRUNNING="TestRunning"      # The test is running
ICA_TESTCOMPLETED="TestCompleted"  # The test completed successfully
ICA_TESTABORTED="TestAborted"      # Error during the setup of the test
ICA_TESTFAILED="TestFailed"        # Error occurred during the test

update_test_state()
{
    echo "${1}" > state.txt
}

install_kvm_dependencies()
{
    update_repos
    install_package aria2
    install_package qemu-kvm
    lsmod | grep kvm_intel
    exit_status=$?
    if [ $exit_status -ne 0 ]; then
        echo "Failed to install KVM"
        update_test_state $ICA_TESTFAILED
        exit 0
    else
        echo "Install KVM succeed"
    fi
    if [ $DISTRO_NAME == "centos" ] || [ $DISTRO_NAME == "rhel" ] || [ $DISTRO_NAME == "oracle" ]; then
        echo "Install epel repository"
        install_epel
        echo "Install qemu-system-x86"
        install_package qemu-system-x86
    fi
    which qemu-system-x86_64
    if [ $? -ne 0 ]; then
        echo "Cannot find qemu-system-x86_64"
        update_test_state $ICA_TESTFAILED
        exit 0
    fi
}

download_image_files()
{
    while echo $1 | grep -q ^-; do
       declare $( echo $1 | sed 's/^-//' )=$2
       shift
       shift
    done
    if [ "x$destination_image_name" == "x" ] || [ "x$source_image_url" == "x" ] ; then
        echo "Usage: GetImageFiles -destination_image_name <destination image name> -source_image_url <source nested image url>"
        update_test_state $ICA_TESTABORTED
        exit 0
    fi
    echo "Downloading $NestedImageUrl..."
    rm -f $destination_image_name
    aria2c -o $destination_image_name -x 10 $source_image_url
    exit_status=$?
    if [ $exit_status -ne 0 ]; then
        echo "Download image fail: $NestedImageUrl"
        update_test_state $ICA_TESTFAILED
        exit 0
    else
        echo "Download image succeed"
    fi
}

start_nested_vm()
{
    while echo $1 | grep -q ^-; do
       declare $( echo $1 | sed 's/^-//' )=$2
       shift
       shift
    done
    cmd=$@

    if [ "x$user" == "x" ] || [ "x$passwd" == "x" ] || [ "x$port" == "x" ] || [ "x$cmd" == "x" ] ; then
        echo "Usage: StartNestedVM -user <username> -passwd <user password> -port <port> <command for start nested kvm>"
        update_test_state $ICA_TESTABORTED
        exit 0
    fi

    echo "Run command: $cmd"
    $cmd
    echo "Wait for the nested VM to boot up ..."
    sleep 10
    retry_times=20
    exit_status=1
    while [ $exit_status -ne 0 ] && [ $retry_times -gt 0 ];
    do
        retry_times=$(expr $retry_times - 1)
        if [ $retry_times -eq 0 ]; then
            echo "Timeout to connect to the nested VM"
            update_test_state $ICA_TESTFAILED
            exit 0
        else
            sleep 10
            echo "Try to connect to the nested VM, left retry times: $retry_times"
            remote_exec -host localhost -user $user -passwd $passwd -port $port "hostname"
            exit_status=$?
        fi
    done
    if [ $exit_status -ne 0 ]; then
        update_test_state $ICA_TESTFAILED
        exit 0
    fi
}

reboot_nested_vm()
{
    while echo $1 | grep -q ^-; do
       declare $( echo $1 | sed 's/^-//' )=$2
       shift
       shift
    done
    if [ "x$user" == "x" ] || [ "x$passwd" == "x" ] || [ "x$port" == "x" ] ; then
        echo "Usage: RebootNestedVM -user <username> -passwd <user password> -port <port>"
        update_test_state $ICA_TESTABORTED
        exit 0
    fi

    echo "Reboot the nested VM"
    remote_exec -host localhost -user $user -passwd $passwd -port $port "echo $passwd | sudo -S reboot"
    echo "Wait for the nested VM to boot up ..."
    sleep 30
    retry_times=20
    exit_status=1
    while [ $exit_status -ne 0 ] && [ $retry_times -gt 0 ];
    do
        retry_times=$(expr $retry_times - 1)
        if [ $retry_times -eq 0 ]; then
            echo "Timeout to connect to the nested VM"
            update_test_state $ICA_TESTFAILED
            exit 0
        else
            sleep 10
            echo "Try to connect to the nested VM, left retry times: $retry_times"
            remote_exec -host localhost -user $user -passwd $passwd -port $port "hostname"
            exit_status=$?
        fi
    done
    if [ $exit_status -ne 0 ]; then
        echo "Timeout to connect to the nested VM"
        update_test_state $ICA_TESTFAILED
        exit 0
    fi
}

stop_nested_vm()
{
    echo "Stop the nested VMs"
    pid=$(pidof qemu-system-x86_64)
    if [ $? -eq 0 ]; then
        kill -9 $pid
    fi
}

enable_root()
{
    while echo $1 | grep -q ^-; do
       declare $( echo $1 | sed 's/^-//' )=$2
       shift
       shift
    done
    if [ "x$user" == "x" ] || [ "x$passwd" == "x" ] || [ "x$port" == "x" ] ; then
        echo "Usage: EnableRoot -user <username> -passwd <user password> -port <port>"
        update_test_state $ICA_TESTABORTED
        exit 0
    fi

    remote_copy -host localhost -user $user -passwd $passwd -port $port -filename ./enableRoot.sh -remote_path /home/$user -cmd put
    remote_exec -host localhost -user $user -passwd $passwd -port $port "chmod a+x /home/$user/*.sh"
    remote_exec -host localhost -user $user -passwd $passwd -port $port "echo $passwd | sudo -S /home/$user/enableRoot.sh -password $passwd"
    if [ $? -eq 0 ]; then
        echo "Root enabled for VM: $image_name"
    else
        echo "Failed to enable root for VM: $image_name"
        update_test_state $ICA_TESTFAILED
        exit 0
    fi
}