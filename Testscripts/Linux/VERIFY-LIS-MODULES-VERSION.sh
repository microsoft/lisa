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
min_supported_distro_version="7.3"
min_supported_LIS_version="4.3.0"

# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

# Check if version is greater than or equal to supported version
function check_version_greater_equal() { test "$(echo "$@" | tr " " "\n" | sort -rV | head -n 1)" == "$1"; }

# Check if vmbus string is recorded in dmesg
hv_string=$(dmesg | grep "Vmbus version:")
if [[ ( $hv_string == "" ) || ! ( $hv_string == *"hv_vmbus:"*"Vmbus version:"* ) ]]; then
    LogErr "Error! Could not find the VMBus protocol string in dmesg."
    SetTestStateAborted
    exit 0
fi

skip_modules=()
config_path="/boot/config-$(uname -r)"
if [[ $(detect_linux_distribution) == clear-linux-os ]]; then
    config_path="/usr/lib/kernel/config-$(uname -r)"
fi

declare -A config_modulesDic
config_modulesDic=([CONFIG_HYPERV=y]="hv_vmbus" [CONFIG_HYPERV_STORAGE=y]="hv_storvsc" [CONFIG_HYPERV_NET=y]="hv_netvsc" [CONFIG_HYPERV_UTILS=y]="hv_utils" 
                   [CONFIG_HID_HYPERV_MOUSE=y]="hid_hyperv" [CONFIG_HYPERV_BALLOON=y]="hv_balloon" [CONFIG_HYPERV_KEYBOARD=y]="hyperv_keyboard")
for key in $(echo ${!config_modulesDic[*]})
do
	module_included=$(grep $key "$config_path")
	if [ "$module_included" ]; then
		skip_modules+=("${config_modulesDic[$key]}")
		LogMsg "Info: Skiping ${config_modulesDic[$key]} module as it is built-in."
	fi
done

# Remove each module in HYPERV_MODULES from skip_modules
for module in "${HYPERV_MODULES[@]}"; do
    skip=""
    for mod_skip in "${skip_modules[@]}"; do
        [[ $module == $mod_skip ]] && { skip=1; break; }
    done
    [[ -n $skip ]] || tempList+=("$module")
done
HYPERV_MODULES=("${tempList[@]}")

if which rpm 2>/dev/null;then
    rpmAvailable=true
else
    rpmAvailable=false
fi

isLISInstalled=$(rpm -qa | grep microsoft-hyper-v 2>/dev/null)

if [ ! -z "$isLISInstalled" ]; then
    expected_lis_version=$(dmesg | grep 'Vmbus LIS version' | awk -F ':' '{print $3}' | tr -d [:blank:])
    if check_version_greater_equal $DISTRO_VERSION $min_supported_distro_version ; then
        HYPERV_MODULES+=('pci_hyperv')
        pci_module=$(lsmod | grep pci_hyperv)
        if [ -z $pci_module ]; then
            modprobe pci_hyperv
        fi
    fi
    if [[ $DISTRO_VERSION =~ 7\.3 ]] || [[ $DISTRO_VERSION =~ 7\.4 ]] ; then
        if check_version_greater_equal $expected_lis_version $min_supported_LIS_version ; then
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
        if [ "$rpmAvailable" = true ] ; then
            if [ ! -z "$isLISInstalled" ]; then
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
fi

exit 0
