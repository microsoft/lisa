#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#####################################################################################
#
# ETHTOOL-GRO-LRO.sh
# Description:
#    This script will first check the existence of ethtool on vm and will 
#   disable & enable generic-receive-offload and large-receive-offload from ethtool.
#
#####################################################################################
# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    SetTestStateAborted
    exit 2
}

# Source constants file and initialize most common variables
UtilsInit

CheckResults()
{
    action="$1"
    conf="$2"
    if [ x"$conf" == x"gro" ]; then
        checkpoint="generic-receive-offload"
    elif [ x"$conf" == x"lro" ]; then
        checkpoint="large-receive-offload"
    fi
    sts=$(ethtool -k "${SYNTH_NET_INTERFACES[@]}" 2>&1 | grep "${checkpoint}" | awk {'print $2'})
    if [ "$action" == "disabled" ] && [ "$sts" == "on" ]; then
        LogMsg "${checkpoint} NOT disabled."
        SetTestStateFailed
        exit 0 
    elif [ "$action" == "enabled" ] && [ "$sts" == "off" ]; then 
        LogMsg "${checkpoint} NOT enabled."
        SetTestStateFailed
        exit 0
    else
        LogMsg "${checkpoint} is $action."
    fi
}

#######################################################################
# Main script body
#######################################################################
# Check if ethtool exist and install it if not
VerifyIsEthtool

GetSynthNetInterfaces
if ! GetSynthNetInterfaces; then
    msg="ERROR: No synthetic network interfaces found"
    LogMsg "$msg"
    SetTestStateFailed
    exit 0
fi

declare -a confArr=("gro" "lro")
for confItem in "${confArr[@]}"; do
    if [ x"$confItem" == x"gro" ]; then
        ckp="generic-receive-offload"
    elif [ x"$confItem" == x"lro" ]; then
        ckp="large-receive-offload"
    fi
    for (( i = 0 ; i < 2 ; i++ )); do
        # Show GRO/LRO status
        sts=$(ethtool -k "${SYNTH_NET_INTERFACES[@]}" 2>&1 | grep ${ckp} | awk {'print $2'})
        if [[ "$sts" == "on" ]];then
            # Disable GRO/LRO
            if ! ethtool -K "${SYNTH_NET_INTERFACES[@]}" ${confItem} off >/dev/null 2>&1;then
                LogMsg "Cannot disable ${ckp}."
                SetTestStateFailed
                exit 0
            fi
            # Check if is disabled
            CheckResults "disabled" "${confItem}"
        elif [[ "$sts" == "off" ]];then
            # Enable GRO/LRO
            if ! ethtool -K "${SYNTH_NET_INTERFACES[@]}" ${confItem} on >/dev/null 2>&1;then
                LogMsg "Cannot enable ${ckp}."
                SetTestStateFailed
                exit 0
            fi
            # Check if is enabled
            CheckResults "enabled" "${confItem}"
        else
            LogMsg "Cannot get status of ${ckp}."
            SetTestStateFailed
            exit 0
        fi
    done
done

SetTestStateCompleted
exit 0
