#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

if [ ! -e ./kvp_client64 ]; then
    echo "the file kvp_client64 does not exist"
    exit 0
fi

chmod 755 ./kvp_client64

# Verify there are no eth devices
echo "Info : Check count of eth devices"
ethCount=$(ls -d /sys/class/net/eth* | wc -l)
echo "Info : ethCount = ${ethCount}"
if [ $ethCount -ne 0 ]; then
    echo "eth device count is not zero: ${ethCount}"
    exit 0
fi

# Create a nonintrinsic HotAddTest KVP item with a value of 'NoNICs'
echo "Info : Creating HotAddTest key with value of 'NoNICS'"
./kvp_client64 append 1 'HotAddTest' 'NoNICs'

# Loop waiting for an eth device to appear
echo "Info : Waiting for an eth device to appear"
timeout=300
noEthDevice=1
while [ $noEthDevice -eq 1 ]
do
    ethCount=$(ls -d /sys/class/net/eth* | wc -l)
    if [[ $ethCount -eq 1 ]]; then
        echo "An eth device was detected"
        break
    fi

    timeout=$((timeout-10))
    sleep 10
    if [ $timeout -le 0 ]; then
        echo "Timed out waiting for eth device to be created"
        exit 0
    fi
done

# Bring up the new eth device
ifup eth0

# Verify the eth device received an IP address
echo "Info : Verify the new NIC received an IPv4 address"
ip addr show eth0 | grep "inet\b"
if [ $? -ne 0 ]; then
    echo "eth0 was not assigned an IPv4 address"
    exit 0
fi

echo "Info : eth0 is up"

# Modify the KVP HotAddTest value to 'NICUp'
echo "Info : Updating HotAddTesk KVP item to 'NICUp'"
./kvp_client64 append 1 'HotAddTest' 'NICUp'

# Loop waiting for the eth device to be removed
echo "Info : Waiting for the eth device to be deleted"
timeout=300
noEthDevice=1
while [ $noEthDevice -eq 1 ]
do
    ethCount=$(ls -d /sys/class/net/eth* | wc -l)
    if [ $ethCount -eq 0 ]; then
        echo "Info : eth count is zero"
        break
    fi

    timeout=$((timeout-10))
    sleep 10
    if [ $timeout -le 0 ]; then
        echo "Timed out waiting for eth device to be hot removed"
        exit 0
    fi
done

# Modify the KVP HotAddTest value to 'NoNICs'
echo "Info : Setting HotAddTest value to 'NoNICs'"
./kvp_client64 append 1 'HotAddTest' 'NoNICs'
echo "Info : Test complete - exiting"
exit 0