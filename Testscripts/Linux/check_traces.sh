#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#####################################################################
# Description:
# This script checks if "Call Trace" message or hot add error appears in
# the system logs and runs in the background.
#####################################################################

# Initializing variables
summary_log=$1
errorHasOccured=0
callTraceHasOccured=0
[[ -f "/var/log/syslog" ]] && logfile="/var/log/syslog" || logfile="/var/log/messages"
[[ -n $summary_log ]] || summary_log="/root/summary.log"

# Checking logs
while true; do
    # Check for hot add errors in dmesg
    dmesg | grep -q "Memory hot add failed"
    if [[ $? -eq 0 ]] && \
        [[ $errorHasOccured -eq 0 ]]; then
        echo "ERROR: 'Memory hot add failed' message is present in dmesg" >> ~/HotAddErrors.log 2>&1
        errorHasOccured=1
    fi

    # Check for call traces in /var/log
    content=$(grep -i "Call Trace" $logfile)
    if [[ -n $content ]] && \
        [[ $callTraceHasOccured -eq 0 ]]; then
        echo "ERROR: System shows Call Trace in $logfile" >> $summary_log 2>&1
        callTraceHasOccured=1
        break
    fi
    sleep 4
done

exit 0