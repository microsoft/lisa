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

exit_code="0"
expected_lis_version=''

# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

# Check if expected LIS version is greater than 4.3.0
function version_ge() { test "$(echo "$@" | tr " " "\n" | sort -rV | head -n 1)" == "$1"; }

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

if rpm -qa | grep hyper-v 2>/dev/null; then
    expected_lis_version=$(dmesg | grep 'Vmbus LIS version' | awk -F ':' '{print $3}' | tr -d [:blank:])
    if [[ $DISTRO_VERSION =~ 7\. ]]; then
        HYPERV_MODULES+=('pci_hyperv')
        pci_module=$(lsmod | grep pci_hyperv)
        if [ -z $pci_module ]; then
            modprobe pci_hyperv
        fi
    fi
    if [[ $DISTRO_VERSION =~ 7\.3 ]] || [[ $DISTRO_VERSION =~ 7\.4 ]] ; then
        if version_ge $expected_lis_version "4.3.0" ; then
            HYPERV_MODULES+=('mlx4_en')
            mlx4_module=$(lsmod | grep mlx4_en)
            if [ -z $mlx4_module ]; then
                modprobe mlx4_en
            fi
        fi
    fi
fi

# Verifies first if the modules are loaded
for module in "${HYPERV_MODULES[@]}"; do
    load_status=$(lsmod | grep "$module" 2>&1)

    # Check to see if the module is loaded
    if [[ $load_status =~ $module ]]; then
        if rpm --help 2>/dev/null; then
            if rpm -qa | grep hyper-v 2>/dev/null; then
                version=$(modinfo "$module" | grep version: | head -1 | awk '{print $2}')
                LogMsg "$module module: ${version}"
                if [ "$module" == "mlx4_en" ] ;then
                    if [ "$MLNX_VERSION" != "$version" ] ;then
                        LogErr "ERROR: Status: $module $version doesnot match with build version $MLNX_VERSION"
                        exit_code="1"
                    fi
                    continue
                fi
                if [ "$expected_lis_version" != "$version" ] ;then
                    LogErr "ERROR: Status: $module $version doesnot match with build version $expected_lis_version"
                    exit_code="1"
                fi
                continue
            fi
        fi
        
        version=$(modinfo "$module" | grep vermagic: | awk '{print $2}')
        if [[ "$version" == "$(uname -r)" ]]; then
            LogMsg "Found a kernel matching version for $module module: ${version}"
        else
            LogErr "Error: LIS module $module doesn't match the kernel build version!"
            exit_code="1"
        fi
    else
         LogErr "Error: LIS module $module is not loaded"
         exit_code="1"
    fi
done

if [ "1" -eq "$exit_code" ]; then
    LogMsg "Exiting with state: TestAborted."
    SetTestStateAborted
else
    LogMsg "Exiting with state: TestCompleted."
    SetTestStateCompleted
    exit 0
fi
