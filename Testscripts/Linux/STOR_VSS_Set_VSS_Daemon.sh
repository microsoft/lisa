#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 2
}

# Source constants file and initialize most common variables
UtilsInit

# Create the state.txt file so ICA knows we are running
SetTestStateRunning
# Set default service name
serviceName="hypervvssd"

if [[ $serviceAction == "start" ]] || [[ $serviceAction == "stop" ]]; then
    LogMsg "service action is $serviceAction"
else
    LogMsg "invalid service action $serviceAction"
    UpdateSummary "invalid action $serviceAction, only support stop and start"
    SetTestStateAborted
    exit 1
fi

GetDistro
case $DISTRO in
    "redhat_7" | "centos_7" | "Fedora" | "mariner")
        serviceName=$(systemctl list-unit-files | grep -e 'hypervvssd\|[h]v-vss-daemon\|[h]v_vss_daemon'| cut -d " " -f 1)
    ;;
    "redhat_6" | "centos_6")
        serviceName=$(chkconfig list | grep -e 'hypervvssd\|[h]v-vss-daemon\|[h]v_vss_daemon'| cut -d " " -f 1)
    ;;
    *)
        LogMsg "Distro $DISTRO is not supported, skipping test."
        UpdateSummary "Distro $DISTRO is not supported, skipping test."
        SetTestStateSkipped
        exit 0
    ;;
esac

for i in $(echo $serviceName | tr "\r" "\n")
do
    LogMsg "service $i $serviceAction"
    service $i $serviceAction || systemctl $serviceAction $i
    if [ $? -ne 0 ]; then
        loginfo="Fail to set VSS Daemon $serviceName as $serviceAction"
        LogErr "$loginfo"
        UpdateSummary "$loginfo"
        SetTestStateFailed
        exit 1
    fi
done
LogMsg "Set VSS Daemon $serviceName as $serviceAction"
SetTestStateCompleted
exit 0
