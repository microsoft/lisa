#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}
UtilsInit


if [ "$(ps aux | grep -c [k]vp)" -lt 1 ]; then
    LogErr "KVP daemon is not running"
    SetTestStateAborted
    exit 0
fi

# Verify OS architecture, select kvp client
if [ "$(uname -a | grep -c x86_64)" -eq 1 ]; then
    LogMsg "64 bit architecture was detected"
    kvp_client="kvp_client64"
elif [ "$(uname -a | grep -c i686)" -eq 1 ]; then
    LogMsg "32 bit architecture was detected"
    kvp_client="kvp_client32"
else
    LogErr "Unable to detect OS architecture"
    SetTestStateAborted
    exit 0
fi

# Append stage 1
value="value"
key="test"
counter=0
while [ "$counter" -le "$Entries" ]; do
    ./"${kvp_client}" append "$Pool" "${key}${counter}" "${value}"
    let counter=counter+1
done


if [ $? -ne 0 ]; then
    LogErr "Failed to append new entries"
    SetTestStateFailed
    exit 0
fi

# Append Stage 2
# kvp_client also deletes entries when appending for the same key
counter=0
while [ "$counter" -le "$Entries" ]; do
    ./"${kvp_client}" append "$Pool" "${key}${counter}" "${value}"
    let counter=counter+1
done

if [ $? -ne 0 ]; then
    LogErr "Failed to replace new entries"
    SetTestStateFailed
    exit 0
fi

# kvp_client can output max 200 entries
expectedEentryCount="$Entries"
if [ "$expectedEentryCount" -gt 200 ]; then
    expectedEentryCount=200
fi
kvp_client_output="$(./${kvp_client} ${Pool})"

if [ "$(echo "${kvp_client_output}" | grep -c "Pool is ${Pool}")" -ne 1 ]; then
    LogErr "Wrong pool otuput"
    LogErr "${kvp_client_output}"
    SetTestStateFailed
    exit 0
fi

# expect more entries than client can output
if [ "$Entries" -gt "$expectedEentryCount" ] && \
    [ "$(echo "$kvp_client_output" | grep -c "Num records is 200")" -lt 1 ] && \
    [ "$(echo "$kvp_client_output" | grep -c "More records available")" -lt 1 ]; then
    LogErr "Not all entries got added"
    LogErr "${kvp_client_output}"
    SetTestStateFailed
    exit 0
fi

if [ $(echo "${kvp_client_output}" | grep -c "Key:.*Value:.*") -ne "$expectedEentryCount" ]; then
    LogErr "Number of Entries doesn't match $expectedEentryCount"
    LogErr "${kvp_client_output}"
    SetTestStateFailed
    exit 0
fi

if [ $(ps aux | grep -c [k]vp) -lt 1 ]; then
    LogErr "KVP daemon failed after append"
    SetTestStateFailed
    exit 0
fi

SetTestStateCompleted