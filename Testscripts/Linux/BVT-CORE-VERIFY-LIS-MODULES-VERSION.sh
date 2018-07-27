#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

########################################################################
#
#   core_verify_lis_version
#
#   Description:
#       This script was created to automate the testing of a Linux
#   Integration services. The script will verify the list of given
#   LIS kernel modules and verify if the version matches with the 
#   Linux kernel release number.
#
#       To pass test parameters into test cases, the host will create
#   a file named constants.sh. This file contains one or more
#   variable definition.
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

# Verifies first if the modules are loaded
for module in "${HYPERV_MODULES[@]}"; do
    load_status=$( lsmod | grep "$module" 2>&1)

    # Check to see if the module is loaded
    if [[ $load_status =~ $module ]]; then
        if rpm --help > /dev/null 2>&1
        then
            if rpm -qa | grep -q hyper-v
            then
                version=$(modinfo "$module" | grep version: | head -1 | awk '{print $2}')
                LogMsg "$module module: ${version}"
                continue
            fi
        fi
        
        version=$(modinfo "$module" | grep vermagic: | awk '{print $2}')
        if [[ "$version" == "$(uname -r)" ]]; then
            LogMsg "Found a kernel matching version for $module module: ${version}"
        else
            LogMsg "Error: LIS module $module doesn't match the kernel build version!"
            SetTestStateAborted
            exit 0
        fi
    fi
done

SetTestStateCompleted
exit 0
