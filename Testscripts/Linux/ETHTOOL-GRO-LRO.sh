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
    case $1 in
        lro)
            feature="large-receive-offload"
            ;;
        gro)
            feature="generic-receive-offload"
            ;;
        *)
            echo "Error: no such feature $2! Exit."
            SetTestStateAborted
            exit 0
            ;;
    esac
    action="$2"
    sts=$(ethtool -k "${SYNTH_NET_INTERFACES[@]}" 2>&1 | grep $feature | awk {'print $2'})
    if [ "$action" == "disabled" ] && [ "$sts" == "on" ]; then
        LogMsg "$feature NOT disabled."
        SetTestStateFailed
        exit 0 
    elif [ "$action" == "enabled" ] && [ "$sts" == "off" ]; then 
        LogMsg "$feature NOT enabled."
        SetTestStateFailed
        exit 0
    else
        LogMsg "$feature is $action."
    fi
}

#######################################################################
# Main script body
#######################################################################
# Check if ethtool exist and install it if not
if ! VerifyIsEthtool; then
    LogErr "Could not find ethtool in the VM"
    SetTestStateFailed
    exit 0
fi

GetSynthNetInterfaces
if ! GetSynthNetInterfaces; then
    msg="ERROR: No synthetic network interfaces found"
    LogMsg "$msg"
    SetTestStateFailed
    exit 0
fi

for (( i = 0 ; i < 2 ; i++ )); do
    # Show GRO status
    sts=$(ethtool -k "${SYNTH_NET_INTERFACES[@]}" 2>&1 | grep generic-receive-offload | awk {'print $2'})
    if [[ "$sts" == "on" ]];then
        # Disable GRO
        if ! ethtool -K "${SYNTH_NET_INTERFACES[@]}" gro off >/dev/null 2>&1;then
            LogMsg "Cannot disable generic-receive-offload."
            SetTestStateFailed
            exit 0
        fi
        # Check if is disabled
        CheckResults "gro" "disabled"
    elif [[ "$sts" == "off" ]];then
        # Enable GRO
        if ! ethtool -K "${SYNTH_NET_INTERFACES[@]}" gro on >/dev/null 2>&1;then
            LogMsg "Cannot enable generic-receive-offload."
            SetTestStateFailed
            exit 0
        fi
        # Check if is enabled
        CheckResults "gro" "enabled"
    else
        LogMsg "Cannot get status of generic-receive-offload."
        SetTestStateFailed
        exit 0
    fi
done

LogMsg "Check - support to update lro or not by filter keyword 'fix' from the line of large-receive-offload."
lro_output=$(ethtool -k "${SYNTH_NET_INTERFACES[@]}" | grep -i large-receive-offload | grep -i fixed)
if [[ $? != 0 ]];then
    for (( i = 0 ; i < 2 ; i++ )); do
        # Show LRO status
        sts=$(ethtool -k "${SYNTH_NET_INTERFACES[@]}" 2>&1 | grep large-receive-offload | awk {'print $2'})
        if [[ "$sts" == "on" ]];then
            # Disable LRO
            if ! ethtool -K "${SYNTH_NET_INTERFACES[@]}" lro off >/dev/null 2>&1;then
                LogMsg "Cannot disable large-receive-offload."
                SetTestStateFailed
                exit 0
            fi
            # Check if is disabled
            CheckResults "lro" "disabled"
        elif [[ "$sts" == "off" ]];then
            # Enable LRO
            if ! ethtool -K "${SYNTH_NET_INTERFACES[@]}" lro on >/dev/null 2>&1;then
                LogMsg "Cannot enable large-receive-offload."
                SetTestStateFailed
                exit 0
            fi
            # Check if is enabled
            CheckResults "lro" "enabled"
        else
            LogMsg "Cannot get status of large-receive-offload."
            SetTestStateFailed
            exit 0
        fi
    done
else
    LogMsg "lro is fixed, can't set value for it, lro output is - $lro_output"
fi

SetTestStateCompleted
exit 0
