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

# Cleanup any old summary.log files
if [ -e ~/summary.log ]; then
    rm -rf ~/summary.log
fi

# Get a list of existing interfaces
# exclude lo loopback device
interfaces=(`ip link | grep '^[0-9]\+:' | awk '{ print $2 }' | grep -v lo | tr -d ':'`)
for int in ${interfaces[*]}; do
    ip link set $int down
    check_exit_status "Bring down interface $int"
done
SetTestStateCompleted
exit 0
