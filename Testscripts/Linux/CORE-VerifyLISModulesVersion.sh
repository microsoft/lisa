#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#   Description:
#   This script was created to automate the testing of a Linux
#   Integration services. The script will verify a list of given
#   LIS kernel modules if are loaded and output the version for each.
#
#   To pass test parameters into test cases, the host will create
#   a file named constants.sh. This file contains one or more
#   variable definition.

hv_string=$(dmesg | grep "Vmbus version:")
MODULES_ERROR=false

ICA_TESTRUNNING="TestRunning"      # The test is running
ICA_TESTCOMPLETED="TestCompleted"  # The test completed successfully
ICA_TESTABORTED="TestAborted"      # Error during setup of test
ICA_TESTFAILED="TestFailed"        # Error during execution of test

CONSTANTS_FILE="constants.sh"

# Source the constants file
if [ -e ./${CONSTANTS_FILE} ]; then
    source ${CONSTANTS_FILE}
else
    LogErr "no ${CONSTANTS_FILE} file"
    SetTestStateFailed
    exit 0
fi

. utils.sh || {
    LogErr "unable to source utils.sh!"
    SetTestStateFailed
    exit 0
}

UtilsInit

# Check if vmbus string is recorded in dmesg
if [[ ( $hv_string == "" ) || ! ( $hv_string == *"hv_vmbus:"*"Vmbus version:"* ) ]]; then
    LogErr "Could not find the VMBus protocol string in dmesg."
    SetTestStateFailed
    exit 0
fi

# Verify first if the LIS modules are loaded
for module in "${HYPERV_MODULES[@]}"; do
    load_status=$(lsmod | grep $module 2>&1)

    # Check to see if the module is loaded
    if [[ $load_status =~ $module ]]; then
        if rpm --help > /dev/null; then
            if rpm -qa | grep hyper-v > /dev/null; then
                version=$(modinfo $module | grep version: | head -1 | awk '{print $2}')
                UpdateSummary "Detected module $module version: ${version}"
                continue
            fi
        fi

        version=$(modinfo $module | grep vermagic: | awk '{print $2}')
        if [[ "$version" == "$(uname -r)" ]]; then
            UpdateSummary "Detected module $module version: ${version}"
        else
            LogErr "LIS module $module doesn't match the kernel build version!"
            MODULES_ERROR=true
        fi
    else
        UpdateSummary "LIS module $module not found!"
        MODULES_ERROR=true
    fi
done

if $MODULES_ERROR; then
    SetTestStateFailed
else
    SetTestStateCompleted
fi
exit 0
