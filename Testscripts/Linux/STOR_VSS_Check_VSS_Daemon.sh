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

#If the system is using systemd we use systemctl
systemctl --version
if [ $? -eq 0 ]; then
    if [[ "$(systemctl is-active hypervvssd)" == "active" ]] || \
       [[ "$(systemctl is-active hv_vss_daemon)" == "active" ]] || \
       [[ "$(systemctl is-active hv-vss-daemon)" == "active" ]]; then

        LogMsg "VSS Daemon is running"
        SetTestStateCompleted
        exit 0

    elif [[ "$(systemctl is-active hypervvssd)" == "unknown" ]] && \
         [[ "$(systemctl is-active hv_vss_daemon)" == "unknown" ]] && \
         [[ "$(systemctl is-active hv-vss-daemon)" == "unknown" ]]; then

        LogMsg "ERROR: VSS Daemon not installed, test aborted"
        SetTestStateAborted
        exit 1

    else
        LogMsg "ERROR: VSS Daemon is installed but not running. Test aborted"
        SetTestStateAborted
        exit 1
    fi

else # For older systems we use ps
    if [[ $(ps -ef | grep 'hypervvssd') ]] || \
       [[ $(ps -ef | grep '[h]v_vss_daemon') ]] || \
       [[ $(ps -ef | grep '[h]v-vss-daemon') ]]; then

        LogMsg "VSS Daemon is running"
        SetTestStateCompleted
        exit 0
    else
        LogMsg "ERROR: VSS Daemon not running, test aborted"
        SetTestStateAborted
        exit 1
    fi
fi
