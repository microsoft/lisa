#!/bin/bash
########################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
########################################################################
########################################################################
#
# Description:
#   This script assumes Xilinx XRT tools are available on the VM
#   and tries to run the validation test to make sure FPGA cards
#   are functional. 
#
#
########################################################################

#######################################################################
function prepare() {
    xrt_setup="/opt/xilinx/xrt/setup.sh"
    if [[ ! -f $xrt_setup ]]; then
        LogErr "$xrt_setup file not found on VM!"
        SetTestStateAborted
        return 1
    fi
    source $xrt_setup
}
function validate_cards() {
    LogMsg "Validating FPGA cards"
    if ! [ -x "$(command -v xbutil)" ]; then
        LogErr "xbutil not found in the path!"
        SetTestStateAborted
        return 1
    fi
    xbutil validate >> TestExecution.log
}

#######################################################################
#
# Main script body
#
#######################################################################
# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}
UtilsInit

prepare
validate_cards

if [ $? -ne 0 ]; then
    LogErr "Could not validate cards!"
    SetTestStateFailed
    exit 0
fi

SetTestStateCompleted
exit 0
