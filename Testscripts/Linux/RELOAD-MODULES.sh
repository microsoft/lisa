#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

########################################################################
#
# Description:
#    This script will first check the existence of LIS modules.
#    Then it will reload the modules in a loop in order to stress the system.
#    It also checks that hv_utils and hyperv_fb cannot be unloaded.
#    When done it will bring up the eth0 interface and check again
#    for the presence of modules.
#
################################################################

# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

# If loopCount is not set, assign 100 by default
if [ "${LoopCount:-UNDEFINED}" = "UNDEFINED" ]; then
    LoopCount=100
fi

HYPERV_MODULES=(hv_vmbus hv_netvsc hv_storvsc hv_utils hv_balloon hid_hyperv hyperv_keyboard hyperv_fb)
MODULES_TO_RELOAD=(hv_netvsc)
MODULES_NOT_TO_RELOAD=(hyperv_fb)
skip_modules=()
config_path=$(get_bootconfig_path)

declare -A config_modulesDic
config_modulesDic=(
[CONFIG_HYPERV=y]="hv_vmbus"
[CONFIG_HYPERV_NET=y]="hv_netvsc"
[CONFIG_HYPERV_STORAGE=y]="hv_storvsc"
[CONFIG_HYPERV_UTILS=y]="hv_utils"
[CONFIG_HYPERV_BALLOON=y]="hv_balloon"
[CONFIG_HID_HYPERV_MOUSE=y]="hid_hyperv"
[CONFIG_HYPERV_KEYBOARD=y]="hyperv_keyboard"
[CONFIG_FB_HYPERV=y]="hyperv_fb"
)
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

if [[ ${#HYPERV_MODULES[@]} -eq 0 ]];then
    LogMsg "All modules are built-in. Skip this case."
    SetTestStateSkipped
    exit 0
fi

VerifyModules()
{
    for module in "${HYPERV_MODULES[@]}"; do
        MODULES=~/modules.txt
        lsmod | grep "hv_*" > $MODULES
        lsmod | grep "hyperv" >> $MODULES
        if ! grep -q "$module" "$MODULES"; then
            LogErr "$module not loaded"
            SetTestStateFailed
            exit 0
        fi
    done
}

BringNetworkUp()
{
    default_route=$(ip route show | grep default)

    ip link set eth0 down
    ip link set eth0 up

    ip route show | grep default
    # Add default route when miss it after run ip link down/up
    if [ $? -ne 0 ]; then
        LogMsg "Run ip route add $default_route"
        ip route add $default_route
    fi

    retryTime=1
    maxRetryTimes=5
    while [ $retryTime -le $maxRetryTimes ]
    do
        LogMsg "Sleep 3 seconds to get eth0 ip for the $retryTime time(s)."
        sleep 3
        ipAddress=$(ip addr show eth0 | grep "inet\b")
        if [ -n "$ipAddress" ];then
            break
        fi
        retryTime=$(($retryTime+1))
    done

    if [ -z "$ipAddress" ]; then
        if ! (dhclient -r && dhclient)
        then
            LogMsg "dhclient exited with an error"
            SetTestStateFailed
            exit 0
        fi
    fi
}

ChangeModule()
{
    # $1 will be the module name
    # $2 will be "-r" or empty
    fail_expected=$3
    if [ -z "$fail_expected" ]; then
        fail_expected="not_expected"
    fi

    sleep 1
    if ! modprobe $2 $1; then
        if [ $fail_expected == "not_expected" ]; then
            LogErr "Module ${1} was expected to be reloaded!"
            modprobe $1
            if [ "$1" == "hv_netvsc" ]; then
                modprobe $1
            fi
            SetTestStateFailed
            exit 0
        fi
    else
        if [ $fail_expected == "expected" ]; then
            LogErr "Module ${1} was not expected to be reloaded!"
            modprobe $1
            SetTestStateFailed
            exit 0
        fi
    fi
}


#######################################################################
#
# Main script body
#
#######################################################################

# install bc tool if not exist
which "bc"
if [ $? -ne 0 ]; then
    update_repos
    install_package bc
fi

# Modules expected not to reload
for module in "${MODULES_NOT_TO_RELOAD[@]}"
do
    if (printf '%s\n' "${HYPERV_MODULES[@]}" | grep -xq $module); then
        ChangeModule $module "-r" "expected"
    fi
done

pass=0
START=$(date +%s)
while [ $pass -lt $LoopCount ]
do
    for module in "${MODULES_TO_RELOAD[@]}"
    do
        if (printf '%s\n' "${HYPERV_MODULES[@]}" | grep -xq $module); then
            ChangeModule $module "-r"
            ChangeModule $module
        fi
    done

    pass=$((pass+1))
    LogMsg "Reload iteration ${pass}"
done

END=$(date +%s)
DIFF=$(echo "$END - $START" | bc)

LogMsg "Finished testing, bringing up eth0"
BringNetworkUp
VerifyModules

ipAddress=$(ip addr show eth0 | grep "inet\b")
if [ -z "$ipAddress" ]; then
    LogMsg "Waiting for interface to receive an IP"
    sleep 30
fi

LogMsg "Test ran for ${DIFF} seconds"
LogMsg "Test Completed Successfully"
SetTestStateCompleted
exit 0
