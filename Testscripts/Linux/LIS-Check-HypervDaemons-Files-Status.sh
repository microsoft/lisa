#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" >state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

#######################################################################
# Check hyper-daemons default files and service status.
# If BuildNumber < 9600, hypervvssd and hypervfcopyd service are inactive,
# only check hypervkvpd
#######################################################################
Check_Hyper_Daemons() {
    BuildNumber=$(dmesg | grep -oP '(?<=Build:).*' | cut -d "-" -f1)
    LogMsg "BuildNumber is: $BuildNumber"
    if [ "$BuildNumber" -lt 9600 ]; then
        hv=('hypervkvpd')
        hv_alias=('[h]v_kvp_daemon')
        hv_service=("hypervkvpd.service")
    else
        hv=('hypervvssd' 'hypervkvpd' 'hypervfcopyd')
        hv_alias=('[h]v_vss_daemon' '[h]v_kvp_daemon' '[h]v_fcopy_daemon')
        hv_service=("hypervkvpd.service" "hypervvssd.service" "hypervfcopyd.service")
    fi
    len_hv=${#hv_service[@]}
    # Start the hyperv daemons check. This is distro-specific.
    GetDistro
    case $DISTRO in
    "redhat_6" | "centos_6")
        for ((i = 0; i < $len_hv; i++)); do
            Check_Daemons_Files "${hv[$i]}"
            Check_Daemons_Status "${hv[$i]}" "${hv_alias[$i]}"
        done
        ;;
    "redhat_7" | "centos_7")
        for ((i = 0; i < $len_hv; i++)); do
            Check_Daemons_Files "${hv_service[$i]}"
            Check_Daemons_Status_RHEL7 "${hv_service[$i]}"
        done
        ;;
    "Fedora")
        for ((i = 0; i < $len_hv; i++)); do
            Check_Daemons_Status_RHEL7 "${hv_service[$i]}"
        done
        ;;
    *)
        LogMsg "Distro not supported. Skip the test."
        SetTestStateSkipped
        exit 0
        ;;
    esac
}
#######################################################################
# Check hyper-v daemons service status under 90-default.preset and
# systemd multi-user.target.wants for rhel7
#######################################################################
Check_Daemons_Files() {
    GetDistro
    case $DISTRO in
    "redhat_6" | "centos_6")
        dameonFile=$(ls /etc/rc.d/init.d | grep -i "$1")
        if [[ "$dameonFile" != $1 ]]; then
            LogMsg "ERROR: $1 is not in /etc/rc.d/init.d , test failed"
            SetTestStateFailed
            exit 0
        fi
        ;;
    "redhat_7" | "centos_7")
        dameonFile=$(ls /usr/lib/systemd/system | grep -i "$1")
        if [[ "$dameonFile" != $1 ]]; then
            LogMsg "ERROR: $1 is not in /usr/lib/systemd/system, test failed"
            SetTestStateFailed
            exit 0
        fi
        # for rhel7.3+(kernel-3.10.0-514), no need to check 90-default.preset
        local kernel=$(uname -r)
        CheckVMFeatureSupportStatus "3.10.0-514"
        if [ $? -ne 0 ]; then
            LogMsg "INFO: Check 90-default.preset for $kernel"
            dameonPreset=$(cat /lib/systemd/system-preset/90-default.preset | grep -i "$1")
            if [ "$dameonPreset" != "enable $1" ]; then
                LogMsg "ERROR: $1 is not in 90-default.preset, test failed"
                SetTestStateFailed
                exit 0
            fi
        else
            LogMsg "INFO: No need to check 90-default.preset for $kernel"
        fi
        ;;
    *)
        LogMsg "Distro not supported. Skip the test."
        SetTestStateSkipped
        exit 0
        ;;
    esac
}
#######################################################################
# Check hyper-v daemons service status is active for rhel7
#######################################################################
Check_Daemons_Status_RHEL7() {
    dameonStatus=$(systemctl is-active "$1")
    if [ "$dameonStatus" != "active" ]; then
        LogMsg "ERROR: $1 is not in running state, test aborted"
        SetTestStateAborted
        exit 0
    fi
}
#######################################################################
# Check hyper-v daemons service status is active
#######################################################################
Check_Daemons_Status() {
    if
        [[ $(ps -ef | grep "$1" | grep -v grep) ]] || \
        [[ $(ps -ef | grep "$2" | grep -v grep) ]]
    then
        LogMsg "$1 Daemon is running"
    else
        LogMsg "ERROR: $1 Daemon not running, test aborted"
        SetTestStateAborted
        exit 0
    fi
}

#######################################################################
# Main script body
#######################################################################
LogMsg "Checking Hyper-V Daemons..."

Check_Hyper_Daemons

SetTestStateCompleted
exit 0
