#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

. utils.sh || {
    echo "Error: unable to source utils.sh!"
    exit 0
}

UtilsInit
homeDir=$(dirname "$0")

if [ ! -e "$homeDir"/tvminfo ]; then
    LogErr "tvminfo tool is not on the system"
    SetTestStateAborted
    exit 0
fi

chmod +x "$homeDir"/tvminfo

sudo "$homeDir"/tvminfo
rc=$?

if [ rc == 0]; then
    UpdateSummary "This OS image is compatible with TVM."
    SetTestStateCompleted
else
    UpdateSummary "This OS image is not compatible with TVM."
    SetTestStateFailed
fi

exit 0
