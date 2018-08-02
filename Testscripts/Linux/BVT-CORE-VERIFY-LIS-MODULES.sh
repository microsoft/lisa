#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

PASS="0"
# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 2
}

# Source constants file and initialize most common variables
UtilsInit

### Display info on the Hyper-V modules that are loaded ###
LogMsg "#### Status of Hyper-V Kernel Modules ####"

#Check if VMBus module exist and if exist continue checking the other modules
hv_string=$(dmesg | grep "Vmbus version:")
if [[ ( $hv_string == "" ) || ! ( $hv_string == *"hv_vmbus:"*"Vmbus version:"* ) ]]; then
    LogMsg "Error! Could not find the VMBus protocol string in dmesg."
    LogMsg "Exiting with state: TestAborted."
    SetTestStateAborted
    exit 0
fi

# Check to see if each module is loaded.
for module in "${HYPERV_MODULES[@]}"; do
    LogMsg "Module: $module"
    load_module=$(dmesg | grep "hv_vmbus: registering driver $module")
    if [[ $load_module == "" ]]; then
        LogMsg "ERROR: Status: $module is not loaded"
        PASS="1"
    else
        LogMsg "$load_module"
        LogMsg "Status: $module loaded!"
    fi
    echo -ne "\\n\\n"
done

#
# Let the caller know everything worked
#
if [ "1" -eq "$PASS" ]; then
    LogMsg "Exiting with state: TestAborted."
    SetTestStateAborted
else 
    LogMsg "Exiting with state: TestCompleted."
    SetTestStateCompleted
    exit 0
fi
