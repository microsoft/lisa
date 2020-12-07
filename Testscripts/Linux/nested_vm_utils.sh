#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# nested_vm_utils.sh
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

# The below echo lines just to avoid the error of SC2034
echo "$ICA_TESTRUNNING"

Update_Test_State()
{
    echo "${1}" > state.txt
}

Install_KVM_Dependencies()
{
    if [ $DISTRO_NAME == "sles" ] || [ $DISTRO_NAME == "sle_hpc" ]; then
        add_sles_network_utilities_repo
    fi
    if [ $DISTRO_NAME == "coreos" ]; then
        LogMsg "Distro not supported. Skip the test."
        SetTestStateSkipped
        exit 0
    fi
    lscpu | grep -i vt
    if [ $? != 0 ]; then
        LogMsg "CPU type is not VT-x. Skip the test."
        SetTestStateSkipped
        exit 0
    fi
    update_repos
    install_package qemu-kvm
    check_package "bridge-utils"
    if [ $? -eq 0 ]; then
        install_package bridge-utils
    fi
    lsmod | grep kvm_intel
    exit_status=$?
    if [ $exit_status -ne 0 ]; then
        LogErr "Failed to install KVM"
        Update_Test_State $ICA_TESTFAILED
        exit 0
    else
        LogMsg "Install KVM succeed"
    fi
    if [ $DISTRO_NAME == "centos" ] || [ $DISTRO_NAME == "rhel" ] || [ $DISTRO_NAME == "oracle" ]; then
        LogMsg "Install epel repository"
        install_epel
        LogMsg "Install qemu-system-x86"
        check_package "qemu-system-x86"
        if [ $? -eq 0 ]; then
            install_package qemu-system-x86
        fi
        [ -f /usr/libexec/qemu-kvm ] && ln -s /usr/libexec/qemu-kvm /sbin/qemu-system-x86_64
    fi
    which qemu-system-x86_64
    if [ $? -ne 0 ]; then
        LogErr "Cannot find qemu-system-x86_64"
        Update_Test_State $ICA_TESTFAILED
        exit 0
    fi
    check_package "aria2"
    if [ $? -eq 0 ]; then
        install_epel
        install_package aria2
    else
        install_package make
        wget https://github.com/q3aql/aria2-static-builds/releases/download/v1.35.0/aria2-1.35.0-linux-gnu-64bit-build1.tar.bz2
        tar -xf aria2-1.35.0-linux-gnu-64bit-build1.tar.bz2
        cd aria2-1.35.0-linux-gnu-64bit-build1/
        make install
        cd ..
    fi
}

Download_Image_Files()
{
    while echo $1 | grep -q ^-; do
       declare $( echo $1 | sed 's/^-//' )=$2
       shift
       shift
    done
    [ ! -d /mnt/resource ] && mkdir /mnt/resource
    if [ "x$destination_image_name" == "x" ] || [ "x$source_image_url" == "x" ] ; then
        LogMsg "Usage: Download_Image_Files -destination_image_name <destination image name> -source_image_url <source nested image url>"
        Update_Test_State $ICA_TESTABORTED
        exit 0
    fi
    LogMsg "Downloading $NestedImageUrl..."
    rm -f /mnt/resource/$destination_image_name
    LogMsg "aria2c -d /mnt/resource -o $destination_image_name -x 10 $source_image_url"
    aria2c -d /mnt/resource -o $destination_image_name -x 10 $source_image_url
    exit_status=$?
    if [ $exit_status -ne 0 ]; then
        LogErr "Download image fail: $NestedImageUrl"
        Update_Test_State $ICA_TESTFAILED
        exit 0
    else
        LogMsg "Download image succeed"
    fi
}

Start_Nested_VM()
{
    while echo $1 | grep -q ^-; do
       declare $( echo $1 | sed 's/^-//' )=$2
       shift
       shift
    done
    cmd=$@

    if [ "x$user" == "x" ] || [ "x$passwd" == "x" ] || [ "x$port" == "x" ] || [ "x$cmd" == "x" ] ; then
        LogMsg "Usage: StartNestedVM -user <username> -passwd <user password> -port <port> <command for start nested kvm>"
        Update_Test_State $ICA_TESTABORTED
        exit 0
    fi

    LogMsg "Run command: $cmd"
    $cmd
    LogMsg "Wait for the nested VM to boot up ..."
    sleep 10
    retry_times=20
    exit_status=1
    while [ $exit_status -ne 0 ] && [ $retry_times -gt 0 ];
    do
        retry_times=$(expr $retry_times - 1)
        if [ $retry_times -eq 0 ]; then
            LogMsg "Timeout to connect to the nested VM"
            Update_Test_State $ICA_TESTFAILED
            exit 0
        else
            sleep 10
            LogMsg "Try to connect to the nested VM, left retry times: $retry_times"
            remote_exec -host localhost -user $user -passwd $passwd -port $port "hostname"
            exit_status=$?
        fi
    done
    if [ $exit_status -ne 0 ]; then
        Update_Test_State $ICA_TESTFAILED
        exit 0
    fi
}

Verify_External_Connection() {
    while echo $1 | grep -q ^-; do
       declare $( echo $1 | sed 's/^-//' )=$2
       shift
       shift
    done
    cmd=$@

    if [ "x$user" == "x" ] || [ "x$passwd" == "x" ] || [ "x$port" == "x" ] ; then
        LogMsg "Usage: ${FUNCNAME[0]} -user <username> -passwd <user password> -port <port>"
        Update_Test_State $ICA_TESTABORTED
        exit 0
    fi

    remote_exec -host localhost -user $user -passwd $passwd -port $port "which curl > /dev/null"
    [ $? == 0 ] || {
        LogErr "No curl in the nested image. Abort the test."
        Update_Test_State $ICA_TESTABORTED
        exit 0
    }
    LogMsg "Downloading file from Internet to the nested VM..."
    output=$(remote_exec -host localhost -user $user -passwd $passwd -port $port "curl -s -S https://github.com > /dev/null")
    [ $? == 0 ] || {
        LogErr "Failed to download a public file"
        LogErr "$output"
        Update_Test_State $ICA_TESTFAILED
        exit 0
    }
    LogMsg "Verify downloading file from Internet to the nested VM: Success"
}

Verify_Host_Connection() {
    while echo $1 | grep -q ^-; do
       declare $( echo $1 | sed 's/^-//' )=$2
       shift
       shift
    done
    cmd=$@

    if [ "x$user" == "x" ] || [ "x$passwd" == "x" ] || [ "x$port" == "x" ] ; then
        LogMsg "Usage: ${FUNCNAME[0]} -user <username> -passwd <user password> -port <port>"
        Update_Test_State $ICA_TESTABORTED
        exit 0
    fi

    LogMsg "Copying file from L1 host to the nested VM..."
    output=$(remote_copy -host localhost -user $user -passwd $passwd -port $port -filename "./constants.sh" -remote_path "/tmp" -cmd "put")
    [ $? == 0 ] || {
        LogErr "Failed to download a public file"
        LogErr "$output"
        Update_Test_State $ICA_TESTFAILED
        exit 0
    }
    LogMsg "Verify copying file from L1 host to the nested VM: Success"
}

Reboot_Nested_VM()
{
    while echo $1 | grep -q ^-; do
       declare $( echo $1 | sed 's/^-//' )=$2
       shift
       shift
    done
    if [ "x$user" == "x" ] || [ "x$passwd" == "x" ] || [ "x$port" == "x" ] ; then
        echo "Usage: RebootNestedVM -user <username> -passwd <user password> -port <port>"
        Update_Test_State $ICA_TESTABORTED
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
            Update_Test_State $ICA_TESTFAILED
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
        Update_Test_State $ICA_TESTFAILED
        exit 0
    fi
}

Stop_Nested_VM()
{
    LogMsg "Stop the nested VMs"
    pid=$(pidof qemu-system-x86_64)
    if [ $? -eq 0 ]; then
        kill -9 $pid
    fi
}

Enable_Root()
{
    while echo $1 | grep -q ^-; do
       declare $( echo $1 | sed 's/^-//' )=$2
       shift
       shift
    done
    if [ "x$user" == "x" ] || [ "x$passwd" == "x" ] || [ "x$port" == "x" ] ; then
        echo "Usage: EnableRoot -user <username> -passwd <user password> -port <port>"
        Update_Test_State $ICA_TESTABORTED
        exit 0
    fi
    remote_copy -host localhost -user $user -passwd $passwd -port $port -filename ./utils.sh -remote_path /home/$user -cmd put
    remote_copy -host localhost -user $user -passwd $passwd -port $port -filename ./enable_root.sh -remote_path /home/$user -cmd put
    remote_exec -host localhost -user $user -passwd $passwd -port $port "chmod a+x /home/$user/*.sh"
    remote_exec -host localhost -user $user -passwd $passwd -port $port "echo $passwd | sudo -S /home/$user/enable_root.sh -password $passwd"
    if [ $? -eq 0 ]; then
        echo "Root enabled for VM: $image_name"
    else
        echo "Failed to enable root for VM: $image_name"
        Update_Test_State $ICA_TESTFAILED
        exit 0
    fi
}

Remote_Exec_Wrapper() {
    user_name=$1
    port=$2
    cmd=$3

    remote_exec -host localhost -user $user_name -passwd $NestedUserPassword -port $port $cmd
}

Remote_Copy_Wrapper() {
    user_name=$1
    port=$2
    file_name=$3
    cmd=$4

    path="/home/$user_name"
    if [ $user_name == "root" ]; then
        path="/root"
    fi

    remote_copy -host localhost -user $user_name -passwd $NestedUserPassword -port $port \
        -filename $file_name -remote_path $path -cmd $cmd
}

Setup_Public_Bridge() {
    br_name=$1
    br_addr=$2
    ip link show $br_name
    if [ $? -eq 0 ]; then
        echo "Bridge $BR_NAME is already up"
        Update_Test_State $ICA_TESTABORTED
        exit 0
    fi
    ip link add $br_name type bridge
    ip link set dev $br_name up
    ip link set dev eth1 master $br_name
    ip addr add $br_addr/24 dev $br_name
    ip link set $br_name up
}

Setup_Tap() {
    tap_name=$1
    br_name=$2
    ip link show $tap_name
    if [ $? -eq 0 ]; then
        echo "Tap $tap_name is already up"
        Update_Test_State $ICA_TESTABORTED
        exit 0
    fi
    echo "Setting up tap $tap_name"
    ip tuntap add $tap_name mode tap user $(whoami) multi_queue
    ip link set $tap_name up
    ip link set $tap_name master $br_name
}

Log_Msg()
{
    echo $(date "+%b %d %Y %T") : "$1" >> $2
}

echo "$ICA_TESTCOMPLETED"
