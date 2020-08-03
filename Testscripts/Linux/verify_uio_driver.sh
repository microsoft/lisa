#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

########################################################################
#
# Description:
#       This script was created to verify the uio_hv_generic module.
#
#       The test performs the following steps:
#         1. Assign a NIC to uio_hv_generic driver and check the uio device
#         2. Restore to hv_netvsc and check the eth1
#
########################################################################

# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

#######################################################################
# Pre-settings & Functions
#######################################################################
# Check distro and kernel version
case "$DISTRO" in
    redhat_7)
        if ! CheckVMFeatureSupportStatus "3.10.0-692"; then
            LogMsg "INFO: this kernel version does not support uio feature, skip test"
            UpdateSummary "INFO: this kernel version does not support uio feature, skip test"
            SetTestStateSkipped
            exit 0
        fi
        ;;
    redhat_8)
        UpdateSummary "$DISTRO support uio feature. Continue."
        ;;
    # TODO: Need to add other distros support, e.g. Ubuntu/SLES...
    *)
        LogMsg "$Distro is not supported in this case now. Skip."
        SetTestStateSkipped
        exit 0
        ;;
esac

# Get device_id and class_id
device_id=$(cat /sys/class/net/eth1/device/device_id | tr -d '{}')
class_id=$(cat /sys/class/net/eth1/device/class_id | tr -d '{}')

function register_uio() {
    LogMsg "Register eth1 to uio"
    output=$(modprobe uio_hv_generic 2>&1)
    lsmod | grep uio_hv_generic
    VerifyExitCodeZero "Verify uio_hv_generic is loaded"

    [ -z "$output" ]
    VerifyExitCodeZero "Verify no output while modprobing uio_hv_generic" "Output: $output"

    echo ${class_id} > /sys/bus/vmbus/drivers/uio_hv_generic/new_id
    echo ${device_id} > /sys/bus/vmbus/drivers/hv_netvsc/unbind
    echo ${device_id} > /sys/bus/vmbus/drivers/uio_hv_generic/bind
    # Verify /dev/uio0 exists
    [ -e /dev/uio0 ]
    VerifyExitCodeZero "Verify /dev/uio0 exists"
}

function recovery() {
    LogMsg "Restore to hv_netvsc"
    echo ${device_id} > /sys/bus/vmbus/drivers/uio_hv_generic/unbind
    echo ${device_id} > /sys/bus/vmbus/drivers/hv_netvsc/bind
    # Verify uio0 is removed and eth1 exists
    [ ! -e /dev/uio0 ]
    VerifyExitCodeZero "Verify /dev/uio0 is removed"
    ip addr show eth1
    VerifyExitCodeZero "Verify eth1 exists"
    # Remove uio_hv_generic module
    rmmod uio_hv_generic
    VerifyExitCodeZero "rmmod uio_hv_generic"
    lsmod | grep uio_hv_generic
    VerifyExitCodeNotZero "Remove uio_hv_generic"
}

register_uio
recovery

SetTestStateCompleted