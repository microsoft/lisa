#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Description:
#   This script will verify a key is present in the speicified pool or not. 
#   The Parameters provided are - Test case number, Key Name. Value, Pool number
#   This test should be run after the KVP Basic test.

CONSTANTS_FILE="constants.sh"

. utils.sh || {
    echo "Error: unable to source utils.sh!"
    exit 0
}

UtilsInit

#
# Source the constants.sh file to pickup definitions from
# the ICA automation
#
if [ -e ./${CONSTANTS_FILE} ]; then
    source ${CONSTANTS_FILE}
else
    LogErr "No ${CONSTANTS_FILE} file"
    SetTestStateAborted
    exit 0
fi

#
# Make sure constants.sh contains the variables we expect
#
if [ "${TC_COVERED:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter TC_COVERED is not defined in ${CONSTANTS_FILE}"
    SetTestStateAborted
    exit 0
fi

if [ "${Key:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter Key is not defined in ${CONSTANTS_FILE}"
    SetTestStateAborted
    exit 0
fi

if [ "${Value:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter Value is not defined in ${CONSTANTS_FILE}"
    SetTestStateAborted
    exit 0
fi

if [ "${Pool:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter Pool number is not defined in ${CONSTANTS_FILE}"
    SetTestStateAborted
    exit 0
fi

UpdateSummary "Covers ${TC_COVERED}"

#
# Verify OS architecture
#
uname -a | grep x86_64
if [ $? -eq 0 ]; then
    msg="64 bit architecture was detected"
    LogMsg "$msg"
    kvp_client="kvp_client64"
else
    uname -a | grep i686
    if [ $? -eq 0 ]; then
        msg="32 bit architecture was detected"
        LogMsg "$msg"
        kvp_client="kvp_client32" 
    else 
        LogErr "Unable to detect OS architecture"
        SetTestStateAborted
        exit 0
    fi
fi

#
# Make sure we have the kvp_client tool
#
if [ ! -e ~/${kvp_client} ]; then
    LogErr "${kvp_client} tool is not on the system"
    SetTestStateAborted
    exit 0
fi

chmod 755 ~/${kvp_client}

#
# verify that the Key Value is present in the specified pool or not.
#
~/${kvp_client} $Pool | grep "${Key}; Value: ${Value}"
if [ $? -ne 0 ]; then
	LogErr "the KVP item is not in the pool"
	SetTestStateFailed
	exit 0
fi

LogMsg "Updating test case state to completed"
SetTestStateCompleted

exit 0