#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#####################################################################################
#
# Disable_enable_GRO_LRO.sh
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
    sts=$(ethtool -k "${SYNTH_NET_INTERFACES[@]}" 2>&1 | grep generic-receive-offload | awk {'print $2'})
    if [ "$action" == "disabled" ] && [ "$sts" == "on" ]; then
        LogMsg "Generic-receive-offload NOT disabled."
        SetTestStateFailed
        exit 0 
    elif [ "$action" == "enabled" ] && [ "$sts" == "off" ]; then 
        LogMsg "Generic-receive-offload NOT enabled."
        SetTestStateFailed
        exit 0
    else
        LogMsg "Generic-receive-offload is $action."
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
        CheckResults "disabled"
    elif [[ "$sts" == "off" ]];then
        # Enable GRO
        if ! ethtool -K "${SYNTH_NET_INTERFACES[@]}" gro on >/dev/null 2>&1;then
            LogMsg "Cannot enable generic-receive-offload."
            SetTestStateFailed
            exit 0
        fi
        # Check if is enabled
        CheckResults "enabled"
    else
        LogMsg "Cannot get status of generic-receive-offload."
        SetTestStateFailed
        exit 0
    fi   
done

# Disable/Enable LRO
LogMsg "LRO status:"
ethtool -k "${SYNTH_NET_INTERFACES[@]}" | grep large-receive-offload 
LogMsg "Enable large-receive-offload:"
ethtool -K "${SYNTH_NET_INTERFACES[[@]}" lro on
LogMsg "LRO status:"
ethtool -k "${SYNTH_NET_INTERFACES[@]}" | grep large-receive-offload
LogMsg "Disable large-receive-offload:"
ethtool -K "${SYNTH_NET_INTERFACES[@]}" lro off

SetTestStateCompleted
exit 0
