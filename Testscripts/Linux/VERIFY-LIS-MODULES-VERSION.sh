#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

########################################################################
#
#   Description:
#       This script was created to automate the testing of a Linux
#   Integration services. The script will verify the list of given
#   LIS kernel modules and verify if the version matches with the
#   Linux kernel release number.
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

# Check if vmbus string is recorded in dmesg
hv_string=$(dmesg | grep "Vmbus version:")
if [[ ( $hv_string == "" ) || ! ( $hv_string == *"hv_vmbus:"*"Vmbus version:"* ) ]]; then
    LogErr "Error! Could not find the VMBus protocol string in dmesg."
    SetTestStateAborted
    exit 0
fi

skip_modules=()
vmbus_included=$(grep CONFIG_HYPERV=y /boot/config-$(uname -r))
if [ "$vmbus_included" ]; then
    skip_modules+=("hv_vmbus")
    LogMsg "Info: Skiping hv_vmbus module as it is built-in."
fi

storvsc_included=$(grep CONFIG_HYPERV_STORAGE=y /boot/config-$(uname -r))
if [ "$storvsc_included" ]; then
    skip_modules+=("hv_storvsc")
    LogMsg "Info: Skiping hv_storvsc module as it is built-in."
fi

# Remove each module in HYPERV_MODULES from skip_modules
for module in "${HYPERV_MODULES[@]}"; do
    skip=""
    for mod_skip in "${skip_modules[@]}"; do
        [[ $module == $mod_skip ]] && { skip=1; break; }
    done
    [[ -n $skip ]] || tempList+=("$module")
done
HYPERV_MODULES=("${tempList[@]}")

# Verifies first if the modules are loaded
for module in "${HYPERV_MODULES[@]}"; do
    load_status=$(lsmod | grep "$module" 2>&1)

    # Check to see if the module is loaded
    if [[ $load_status =~ $module ]]; then
        if rpm --help 2>/dev/null; then
            if rpm -qa | grep hyper-v 2>/dev/null; then
                version=$(modinfo "$module" | grep version: | head -1 | awk '{print $2}')
                LogMsg "$module module: ${version}"
                continue
            fi
        fi
        
        version=$(modinfo "$module" | grep vermagic: | awk '{print $2}')
        if [[ "$version" == "$(uname -r)" ]]; then
            LogMsg "Found a kernel matching version for $module module: ${version}"
        else
            LogErr "Error: LIS module $module doesn't match the kernel build version!"
            SetTestStateAborted
            exit 0
        fi
    fi
done

SetTestStateCompleted
exit 0
