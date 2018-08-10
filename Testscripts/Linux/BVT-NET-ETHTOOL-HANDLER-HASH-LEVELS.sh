#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#############################################################################
#
# Ethtool_Handler_HashLevels.sh
# Description:
#   This script will first check the existence of ethtool on vm and that
#   the network flow hashing options are supported from ethtool.
#   While L4 hash is enabled by default the script will try to exclude it and 
#   included back. It will check each time if the results are as expected.
#############################################################################
# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

CheckResults()
{
    action="$2"
    status="$1"
    if [[ "$status" = *"Operation not supported"* ]]; then
        LogMsg "$status"
        LogMsg "Operation not supported. Test Skipped."
        SetTestStateAborted
        exit 0
    fi
    LogMsg "$status"

    if [[ "$action" ]]; then
        sts=$(ethtool -n "${SYNTH_NET_INTERFACES[@]}" rx-flow-hash "$protocol" 2>&1)
        if [ "$action" == "excluded" ] && [[ "$sts" = *"[TCP/UDP src port]"* && "$sts" = *"[TCP/UDP dst port]"* ]]; then
            LogMsg "$sts"
            LogMsg "Protocol: $protocol NOT excluded."
            SetTestStateFailed
            exit 0
        elif [ "$action" == "included" ] && ! [[ "$sts" = *"[TCP/UDP src port]"* && "$sts" = *"[TCP/UDP dst port]"* ]]; then
            LogMsg "$sts"
            LogMsg "Protocol: ${protocol} NOT included."
            SetTestStateFailed
            exit 0
        else
            LogMsg "$sts"
            LogMsg "Protocol: ${protocol} ${action}."
        fi
    fi
}

#######################################################################
# Main script body
#######################################################################
# Check if ethtool exist and install it if not
VerifyIsEthtool

if ! GetSynthNetInterfaces; then
    msg="ERROR: No synthetic network interfaces found"
    LogMsg "$msg"
    SetTestStateFailed
    exit 0
fi

# Check if kernel support network flow hashing options with ethtool
sts=$(ethtool -n "${SYNTH_NET_INTERFACES[@]}" rx-flow-hash "$protocol" 2>&1)
CheckResults "$sts"

# L4 hash is enabled as default
# Try to exclude TCP/UDP port numbers in hashing
if ! ethtool -N "${SYNTH_NET_INTERFACES[@]}" rx-flow-hash "$protocol" sd 2>&1; then
    LogMsg "Error: Cannot exclude $protocol!"
    SetTestStateFailed
    exit 0
fi

# Check if operation is supported and if was excluded
CheckResults "$sts" "excluded"

# Try to include TCP/UDP port numbers in hashing
if ! ethtool -N "${SYNTH_NET_INTERFACES[@]}" rx-flow-hash "$protocol" sdfn 2>&1;then
    LogMsg "Error: Cannot include $protocol!"
    SetTestStateFailed
    exit 0
fi

# Check if operation is supported and if was included
CheckResults "$sts" "included"

LogMsg "Exclude/Include ${protocol} on ${SYNTH_NET_INTERFACES[*]} successfully."
SetTestStateCompleted
exit 0
