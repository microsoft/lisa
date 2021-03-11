#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Description:
# This script was created to automate the testing of L3 Cache spread.
# The L3 cache must be mapped to the socket for each of the NUMA nodes.
# An incorrect mapping would be for the L3 cache to be assigned on per VM core.

# Exception: https://t.ly/x8k3
# if numa=off is defined in /proc/cmdline and kernel version is earlier than 2.6.37,
# the test will be skipped.
. utils.sh || {
    echo "unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 1
}

UtilsInit

if ! which lscpu; then
    install_package util-linux
fi

kj=$(uname -r | cut -d '-' -f 1 | cut -d '.' -f 1)
kn=$(uname -r | cut -d '-' -f 1 | cut -d '.' -f 2)
kr=$(uname -r | cut -d '-' -f 1 | cut -d '.' -f 3)
if [[ $(cat /proc/cmdline | grep numa=off) ]]; then
    LogMsg "Found numa=off in /proc/cmdline. Checking the kernel version."
    if [[ $kj -le 2 && $kn -le 6 && $kr -le 37 ]]; then
        LogErr "This kernel has numa=off in boot parameter and its kernel version is earlier than 2.6.37. No support for NUMA setting. https://t.ly/x8k3"
        SetTestStateSkipped
        exit 0
    fi
fi

lscpu --extended=cpu,node,socket,cache > lscpu.log
# change cache column separator
sed -i 's/:/ /g' lscpu.log

# we don't need the table header
sed -i 's/^CPU.*//g' lscpu.log
sed -i '/^$/d' lscpu.log

# Print the content of lscpu.log
LogMsg "Output of lscpu --extended=cpu,node,socket,cache command:"
LogMsg "$(cat lscpu.log)"

# table header should now look like this:
# CPU NODE SOCKET L1d L1i L2 L3

while read line;
do
    # Test case L3 CACHE Spread on NUMA nodes
    # Each line in the file details the mapping of one CPU core.
    # The L3 cache of each core must be mapped to the
    # NUMA node that core belongs to instead of the core itself.

    # Corect mapping:
    # CPU NODE SOCKET L1d L1i L2 L3
    # 8   0    0      8   8   8  0
    # 9   1    1      9   9   9  1

    # Inorect mapping:
    # CPU NODE SOCKET L1d L1i L2 L3
    # 8   0    0      8   8   8  8
    # 9   1    1      9   9   9  9

    # Current core number
    core=$(echo "$line" | awk '{ print $1 }')
    # NUMA Node the current core is assigned to.
    node=$(echo "$line" | awk '{ print $2 }')
    # L3 Cache mapping for the current core.
    l3Cache=$(echo "$line" | awk '{ print $7 }')
    if [ "$l3Cache" -ne "$node" ]; then
        LogErr "Core $core L3 Cache should be mapped to NUMA node $node, actual: $l3Cache"
        SetTestStateFailed
        exit 0
    fi
done < lscpu.log

LogMsg "Test completed successfully"
SetTestStateCompleted
exit 0
