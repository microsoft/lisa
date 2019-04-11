#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Description:
#   This script verifies that the link status of a disconnected NIC is down.
#
#   Steps:
#   1. Verify configuration file constants.sh
#   2. Determine interface(s) to check
#   3. Check operstate
#
##############################################################################
# Source utils.sh
. utils.sh || {
    echo "unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}
# Source constants file and initialize most common variables
UtilsInit

# Parameter provided in constants file
declare __iface_ignore
if [ "${ipv4:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter ipv4 is not defined in constants file! Make sure you are using the latest LIS code."
    SetTestStateFailed
    exit 0
else
    CheckIP "$ipv4"
    if [ 0 -ne $? ]; then
        LogErr "Test parameter ipv4 = $ipv4 is not a valid IP Address"
        SetTestStateFailed
        exit 0
    fi
    # Get the interface associated with the given ipv4
    __iface_ignore=$(ip -o addr show | grep "$ipv4" | cut -d ' ' -f2)
fi

# Retrieve synthetic network interfaces
GetSynthNetInterfaces
if [ 0 -ne $? ]; then
    LogMsg "Warning: No synthetic network interfaces found"
else
    # Remove interface if present
    SYNTH_NET_INTERFACES=(${SYNTH_NET_INTERFACES[@]/$__iface_ignore/})
    if [ ${#SYNTH_NET_INTERFACES[@]} -eq 0 ]; then
        LogMsg "The only synthetic interface is the one which LIS uses to send files/commands to the VM."
    fi
    LogMsg "Found ${#SYNTH_NET_INTERFACES[@]} synthetic interface(s): ${SYNTH_NET_INTERFACES[*]} in VM"

    declare __synth_iface
    for __synth_iface in ${SYNTH_NET_INTERFACES[@]}; do
        if [ ! -e /sys/class/net/"$__synth_iface"/operstate ]; then
            LogErr "Could not find /sys/class/net/$__synth_iface/operstate ."
            SetTestStateFailed
            exit 0
        fi

        __state=$(cat /sys/class/net/"${__synth_iface}"/operstate)
        if [ "$__state" != "down" ]; then
            LogErr "Operstate of $__synth_iface is not down. It is $__state"
            SetTestStateFailed
            exit 0
        fi
        LogMsg "Operstate is $__state"
    done
fi

# Get the legacy netadapter interface
GetLegacyNetInterfaces
if [ 0 -ne $? ]; then
    LogMsg "No legacy network interfaces found"
else
    # Remove loopback interface
    LEGACY_NET_INTERFACES=(${LEGACY_NET_INTERFACES[@]/lo/})
    if [ ${#LEGACY_NET_INTERFACES[@]} -eq 0 ]; then
        LogMsg "The only legacy interface is the loopback interface lo, which was set to be ignored."
    else
        # Remove interface if present
        LEGACY_NET_INTERFACES=(${LEGACY_NET_INTERFACES[@]/$__iface_ignore/})
        if [ ${#LEGACY_NET_INTERFACES[@]} -eq 0 ]; then
            LogMsg "The only legacy interface is the one which LIS uses to send files/commands to the VM."
        else
            LogMsg "Found ${#LEGACY_NET_INTERFACES[@]} legacy interface(s): ${LEGACY_NET_INTERFACES[*]} in VM"
            declare __legacy_iface
            for __legacy_iface in ${LEGACY_NET_INTERFACES[@]}; do
                if [ ! -e /sys/class/net/"$__legacy_iface"/operstate ]; then
                    LogErr "Could not find /sys/class/net/$__legacy_iface/operstate ."
                    SetTestStateFailed
                    exit 0
                fi

                __state=$(cat /sys/class/net/"${__legacy_iface}"/operstate)
                if [ "$__state" != "down" ]; then
                    LogErr "Operstate of $__legacy_iface is not down. It is $__state"
                    SetTestStateFailed
                    exit 0
                fi
            done
        fi
    fi
fi

# test if there was any "check"-able interface at all
if [ ${#SYNTH_NET_INTERFACES[@]} -eq 0 -a ${#LEGACY_NET_INTERFACES[@]} -eq 0 ]; then
    LogErr "No suitable test interface found."
    SetTestStateFailed
    exit 0
fi

# everything ok
LogMsg "Updating test case state to completed"
SetTestStateCompleted
exit 0