#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" >state.txt
    exit 2
}

# Source constants file and initialize most common variables
UtilsInit

systemctl --version
if [ $? -eq 0 ]; then
    vss_service_name=$(systemctl | grep vss | awk '{print $1}' | tail -1)
    
    if [ "$(systemctl is-active ${vss_service_name})" == "active" ]; then
        LogMsg "VSS Daemon is running, we will try to stop it gracefully"
        systemctl stop $vss_service_name
        if [ $? -ne 0 ]; then
            LogErr "ERROR: Failed to stop VSS Daemon"
            SetTestStateAborted
        fi

        LogMsg "Successfully stopped the VSS Daemon"
        SetTestStateCompleted

    elif [ "$(systemctl is-active ${vss_service_name})" == "unknown" ]; then
        LogErr "ERROR: VSS Daemon not installed, test aborted"
        SetTestStateAborted

    else
        LogMsg "Warning: VSS Daemon is installed but not running"
        SetTestStateCompleted
    fi

else
    if [[ $(ps -ef | grep 'hypervvssd') ]] || \
       [[ $(ps -ef | grep '[h]v_vss_daemon') ]]; then

        LogMsg "VSS Daemon is running"
        vss_pid=$(ps aux | grep vss | head -1 | awk '{print $2}')
        kill $vss_pid
        
        if [ $? -ne 0 ]; then
            LogErr "ERROR: Failed to stop VSS Daemon"
            SetTestStateAborted
        fi
        LogMsg "Successfully stopped the VSS Daemon"
        SetTestStateCompleted

    else
        LogErr "ERROR: VSS Daemon not running, test aborted"
        SetTestStateAborted
    fi
fi
