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

exit_code=0
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

GetDistro

case $DISTRO in
    redhat_*|centos_*)
        # Check if vmbus string is recorded in dmesg
        hv_string=$(dmesg | grep "Vmbus version:")
        if [[ ( $hv_string == "" ) || ! ( $hv_string == *"hv_vmbus:"*"Vmbus version:"* ) ]]; then
            LogErr "Could not find the VMBus protocol string in dmesg. Test stopped here."
            SetTestStateAborted
            exit 0
        fi

        skip_modules=()
        config_path=$(get_bootconfig_path)
        LogMsg "Set the configuration path to $config_path"

        declare -A config_modulesDic
        config_modulesDic=(
        [CONFIG_HYPERV=y]="hv_vmbus"
        [CONFIG_HYPERV_STORAGE=y]="hv_storvsc"
        [CONFIG_HYPERV_NET=y]="hv_netvsc"
        [CONFIG_HYPERV_UTILS=y]="hv_utils"
        [CONFIG_HID_HYPERV_MOUSE=y]="hid_hyperv"
        [CONFIG_HYPERV_BALLOON=y]="hv_balloon"
        [CONFIG_HYPERV_KEYBOARD=y]="hyperv_keyboard"
        )
        for key in $(echo ${!config_modulesDic[*]})
        do
            module_included=$(grep $key "$config_path")
            if [ "$module_included" ]; then
                skip_modules+=("${config_modulesDic[$key]}")
                LogMsg "Skipping the built-in modules, ${config_modulesDic[$key]}"
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
        LogMsg "Target module names: ${HYPERV_MODULES[*]}"

        if [ ! $HYPERV_MODULES ]; then
            LogErr "Target module is empty or null"
            exit_code=$((exit_code+1))
        fi

        if which rpm 2>/dev/null;then
            rpmAvailable=true
            isLISInstalled=$(rpm -qa | grep microsoft-hyper-v 2>/dev/null)
            LogMsg "The current LIS installation state: $isLISInstalled"
        else
            rpmAvailable=false
            isLISInstalled=''
            LogMsg "The current LIS installation state: none"
            LogErr "Test Skipped because of no LIS installation"
            SetTestStateSkipped
            exit 0
        fi
        LogMsg "RPM availability in the system: $rpmAvailable"

        if [ ! -z "$isLISInstalled" ]; then
            expected_lis_version=$(dmesg | grep -i 'Vmbus LIS version' | awk -F ':' '{print $3}' | tr -d [:blank:])
            if check_version_greater_equal $DISTRO_VERSION $min_supported_distro_version ; then
                HYPERV_MODULES+=('pci_hyperv')
                pci_module=$(lsmod | grep pci_hyperv)
                if [[ -z "${pci_module}" ]]; then
                    modprobe pci_hyperv
                    LogMsg "pci_hyperv module loaded"
                fi
            fi
            if [[ $DISTRO_VERSION =~ 7\.3 ]] || [[ $DISTRO_VERSION =~ 7\.4 ]] ; then
                if check_version_greater_equal $expected_lis_version $min_supported_LIS_version ; then
                    HYPERV_MODULES+=('mlx4_en')
                    mlx4_module=$(lsmod | grep mlx4_en)
                    if [[ -z "$mlx4_module" ]]; then
                        modprobe mlx4_en
                        LogMsg "mlx4_en module loaded"
                    fi
                fi
            fi
        fi

        # Verifies first if the modules are loaded
        for module in "${HYPERV_MODULES[@]}"; do
            load_status=$(lsmod | grep "$module" 2>&1)

            # Check to see if the module is loaded
            if [[ $load_status =~ $module ]]; then
                LogMsg "LIS module $module loaded successfully"
                if [ "$rpmAvailable" = true ] && [ ! -z "$isLISInstalled" ]; then
                    version=$(modinfo "$module" | grep version: | head -1 | awk '{print $2}')
                    LogMsg "$module module version: ${version}"
                    if [[ "$module" == "mlx4_en" && "$MLNX_VERSION" != "$version" ]] ;then
                        LogErr "Status: $module $version did not match to the build one, $MLNX_VERSION"
                        exit_code=$((exit_code+1))
                    else
                        continue
                    fi
                    if [[ "$expected_lis_version" != "$version" ]] ;then
                        LogErr "Status: $module $version did not match to the build one, $expected_lis_version"
                        exit_code=$((exit_code+1))
                    else
                        continue
                    fi
                fi

                version=$(modinfo "$module" | grep vermagic: | awk '{print $2}')
                if [[ "$version" == "$(uname -r)" ]]; then
                    LogMsg "Found the matching kernel version of $module module: ${version}"
                else
                    LogErr "LIS module $module did not match the kernel build version!"
                    exit_code=$((exit_code+1))
                fi
            else
                LogErr "LIS module $module was not loaded"
                exit_code=$((exit_code+1))
            fi
        done

        if [ 0 -eq $exit_code ]; then
            LogMsg "Exiting with state: $__LIS_TESTCOMPLETED."
            SetTestStateCompleted
        else
            LogMsg "Exiting with state: $__LIS_TESTABORTED."
            SetTestStateAborted
        fi
    ;;
    *)
        LogErr "$DISTRO is not supported in this test"
        SetTestStateSkipped
    ;;
esac
exit 0
