#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

########################################################################
#
## Description:
#       This script was created to automate the testing of a Linux
#       Integration services. This script will verify that the
#       VMBus protocol string is identified and present in Linux.
#       This is available only for Windows Server 2012 R2 and newer.
#       Windows Server 2012 R2 VMBus protocol version is 2.4, newer
#       Linux kernels have VMBus protocol version 3.0.
#
#       The test performs the following steps:
#         1. Looks for the VMBus protocol tag inside the dmesg log.
#
#
################################################################

# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

function verify_vmbus_protocol_version() {
    #
    # Checking for the VMBus protocol string in dmesg
    #
    vmbus_string=$(dmesg | grep -oE '*hv_vmbus.*Vmbus.*version.*')
    if [[ "$vmbus_string" == "" ]]; then
        UpdateSummary "Could not find the VMBus protocol string in dmesg."
        SetTestStateFailed
        exit 0
    fi
    UpdateSummary "Found a matching VMBus string: ${vmbus_string}"
    SetTestStateCompleted
}

verify_vmbus_protocol_version