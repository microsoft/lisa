#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#############################################################################
#
# Description:
#    This script will first check the existence of ethtool on vm and will
#    set the driver message type flags by name/number and get the driver
#    message type flags from ethtool.
#
#############################################################################
# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

#######################################################################
# Main script body
#######################################################################
# Check if feature is supported by the kernel
if ! which nm; then
    update_repos
    install_package binutils
fi

kernel_version=$(uname -r)
# if the module is not builtin
if [ $(grep -c netvsc < /lib/modules/"$kernel_version"/modules.builtin) == 0 ]; then
    # get the path to the netvsc kernel module
    kernel_module=$(ls /lib/modules/"$kernel_version"/kernel/drivers/net/hyperv/hv_netvsc.ko*)
    # if the module is archived as xz, extract it to check symbols
    if [ $(echo "$kernel_module" | grep -c ".xz") -ne 0 ]; then
        cp "$kernel_module" .
        xz -d $(basename $kernel_module)
        kernel_module=$(ls hv_netvsc*)
    fi
    msg_level_symbols=$(nm "$kernel_module" | grep msglevel)
    if [[ "$msg_level_symbols" != *netvsc_get_msglevel* ]] || [[ "$msg_level_symbols" != *netvsc_set_msglevel* ]]; then
        UpdateSummary "Getting / Setting the driver message type flags from ethtool is not supported on $kernel_version, skipping test."
        SetTestStateSkipped
        exit 0
    fi
fi

# Check if ethtool exist and install it if not
VerifyIsEthtool

if ! GetSynthNetInterfaces; then
    LogErr "No synthetic network interfaces found"
    SetTestStateFailed
    exit 0
fi

net_interface=${SYNTH_NET_INTERFACES[0]}
LogMsg "The network interface is $net_interface"

# Try to set the driver message type flags by name
testflag1="tx_done"
testflag2="rx_status"
LogMsg "Try to set $testflag1 and $testflag2 flags on $net_interface"
sts=$(ethtool -s "${net_interface}" msglvl "$testflag1" on "$testflag2" on 2>&1)
if [[ "$sts" = *"Operation not supported"* ]]; then
    LogErr "$sts"
    LogErr "Setting the driver message type flags from ethtool is not supported on $kernel_version"
    SetTestStateFailed
    exit 0
fi

CheckNetInterfaceFlag()
{
    if ! ethtool "${net_interface}" | grep "$1"; then
        LogErr "Cannot get the $1 flag from $net_interface"
        SetTestStateFailed
        exit 0
    else
        LogMsg "Get the $1 flag from $net_interface"
    fi
}

# Check if the above operation really worked
CheckNetInterfaceFlag "$testflag1"
CheckNetInterfaceFlag "$testflag2"

# Try to unset the driver message type flags by name
LogMsg "Try to unset $testflag1 flag on $net_interface"
if ! ethtool -s "${net_interface}" msglvl "$testflag1" off; then
    LogErr "Cannot unset $testflag1"
    SetTestStateFailed
    exit 0
fi

# Check if the above operation really worked
ethtool "${net_interface}" | grep "$testflag1"
if [ $? == 0 ]; then
    LogMsg "Error: Cannot unset $testflag1 flag"
    SetTestStateFailed
    exit 0
fi

# Try to set the driver message type flags by number
# probe 0x0002 Hardware probing
testflag3="0x0002"
if ! ethtool -s "${net_interface}" msglvl "$testflag3"; then
    LogMsg "Error: Cannot set $testflag3"
    SetTestStateFailed
    exit 0
fi

CheckNetInterfaceFlag "probe"

LogMsg "Set/Unset the driver message type flags on on ${net_interface} successfully."
SetTestStateCompleted
exit 0
