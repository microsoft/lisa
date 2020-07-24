#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

. utils.sh || {
    echo "Error: unable to source utils.sh!"
    exit 0
}

UtilsInit
homeDir=$(dirname "$0")

if [ ! -e $homeDir/sbinfo ]; then
    LogErr "sbinfo tool is not on the system"
    SetTestStateAborted
    exit 0
fi

chmod +x $homeDir/sbinfo

SBEnforcementStage=$(sudo ${homeDir}/sbinfo | grep SBEnforcementStage | sed -e s/'  "SBEnforcementStage": '//)
LogMsg "$SBEnforcementStage"

if [[ "$SBEnforcementStage" == *"Secure Boot is enforced"* ]] || [[ "$SBEnforcementStage" == *"Secure Boot is not enforced"* ]]; then
    UpdateSummary "This OS image is compatible with Secure Boot."

    SetTestStateCompleted
    exit 0
fi

UpdateSummary "This OS image is not compatible with Secure Boot."

SetTestStateFailed
exit 0
